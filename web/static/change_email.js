/* gpt_signup_hybrid - Đổi Email tab logic.
 *
 * 2 khung nhập:
 *   - Tài khoản 1Zone: email|password (account cũ, sẽ bị đổi email)
 *   - Mailbox mới:      email|pwd|refresh_token|client_id (email đổi sang)
 *
 * Manager ghép cặp tuần tự; account/mailbox đã dùng thành công ở lần chạy
 * trước bị loại tự động (tránh đổi trùng). Output: `mailcu|mailmoi|pass`.
 */
(function () {
  'use strict';

  if (document.querySelector('.tab-btn[data-tab="change-email"]') === null) return;

  const LS_ACCOUNTS_CE = 'gpt_reg.change_email_accounts';
  const LS_MAILBOXES_CE = 'gpt_reg.change_email_mailboxes';

  const dom = {
    accountInput: document.getElementById('ce-account-input'),
    mailboxInput: document.getElementById('ce-mailbox-input'),
    engine: document.getElementById('ce-engine'),
    candidate: document.getElementById('ce-candidate'),
    category: document.getElementById('ce-category'),
    captchaMode: document.getElementById('ce-captcha-mode'),
    maxConcurrent: document.getElementById('ce-max-concurrent'),
    jobTimeout: document.getElementById('ce-job-timeout'),
    pollTimeout: document.getElementById('ce-poll-timeout'),
    minSeconds: document.getElementById('ce-min-seconds'),
    yescaptchaKey: document.getElementById('ce-yescaptcha-key'),
    proxyToggle: document.getElementById('ce-proxy-toggle'),
    headlessToggle: document.getElementById('ce-headless-toggle'),
    runNote: document.getElementById('ce-run-note'),
    usedSummary: document.getElementById('ce-used-summary'),
    toggleHistory: document.getElementById('ce-btn-toggle-history'),
    historyList: document.getElementById('ce-history-list'),
    accountCount: document.getElementById('ce-account-count'),
    mailboxCount: document.getElementById('ce-mailbox-count'),
    btnRun: document.getElementById('ce-btn-run'),
    btnStopAll: document.getElementById('ce-btn-stop-all'),
    btnClearInput: document.getElementById('ce-btn-clear-input'),
    btnClearUsed: document.getElementById('ce-btn-clear-used'),
    btnRetryFailed: document.getElementById('ce-btn-retry-failed'),
    btnClearDone: document.getElementById('ce-btn-clear-done'),
    btnClearAll: document.getElementById('ce-btn-clear-all'),
    btnCopySuccess: document.getElementById('ce-btn-copy-success'),
    btnCopyError: document.getElementById('ce-btn-copy-error'),
    jobSummary: document.getElementById('ce-job-summary'),
    jobList: document.getElementById('ce-job-list'),
    successPane: document.getElementById('ce-success-pane'),
    errorPane: document.getElementById('ce-error-pane'),
    logTarget: document.getElementById('ce-log-target'),
    logPane: document.getElementById('ce-log-pane'),
  };

  let _state = { jobs: [], used_accounts: [], used_mailboxes: [] };
  let _selectedJobId = null;

  function api(path, opts = {}) {
    const token = window.GptUi.getAuthToken();
    const headers = {
      'Content-Type': 'application/json',
      ...(token ? { 'X-API-Token': token } : {}),
      ...(opts.headers || {}),
    };
    return fetch(path, { ...opts, headers }).then(async (r) => {
      if (!r.ok) {
        let detail = `HTTP ${r.status}`;
        try {
          const body = await r.json();
          if (body && body.detail) detail = String(body.detail);
        } catch (_) { /* non-JSON body */ }
        throw new Error(detail);
      }
      return r.json();
    });
  }

  function escHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }

  function countLines(text) {
    return text.split('\n').filter((l) => {
      const s = l.trim();
      return s && !s.startsWith('#');
    }).length;
  }

  function updateCounts() {
    dom.accountCount.textContent = `${countLines(dom.accountInput.value)} accounts`;
    dom.mailboxCount.textContent = `${countLines(dom.mailboxInput.value)} mailboxes`;
  }

  function persist() {
    if (window.GptUi.persistTextarea) {
      window.GptUi.persistTextarea(LS_ACCOUNTS_CE, dom.accountInput.value);
      window.GptUi.persistTextarea(LS_MAILBOXES_CE, dom.mailboxInput.value);
    }
  }

  function loadPersisted() {
    try {
      const a = localStorage.getItem(LS_ACCOUNTS_CE);
      const m = localStorage.getItem(LS_MAILBOXES_CE);
      if (a !== null) dom.accountInput.value = a;
      if (m !== null) dom.mailboxInput.value = m;
    } catch (_) { /* ignore */ }
  }

  function renderUsed() {
    const used = _state.used_accounts || [];
    const mailboxes = _state.used_mailboxes || [];
    dom.usedSummary.textContent =
      `Đã dùng: ${used.length} account · ${mailboxes.length} mailbox`;
  }

  // ── Config load/save ─────────────────────────────────────────────

  function applyConfig(cfg) {
    if (!cfg) return;
    if (cfg.engine && dom.engine.querySelector(`option[value="${cfg.engine}"]`)) {
      dom.engine.value = cfg.engine;
    }
    if (cfg.candidate) dom.candidate.value = cfg.candidate;
    if (cfg.category) dom.category.value = cfg.category;
    if (cfg.captcha_mode && dom.captchaMode.querySelector(`option[value="${cfg.captcha_mode}"]`)) {
      dom.captchaMode.value = cfg.captcha_mode;
    }
    if (cfg.max_concurrent) dom.maxConcurrent.value = cfg.max_concurrent;
    if (cfg.job_timeout) dom.jobTimeout.value = cfg.job_timeout;
    if (cfg.poll_timeout_seconds) dom.pollTimeout.value = cfg.poll_timeout_seconds;
    if (typeof cfg.min_seconds === 'number') dom.minSeconds.value = cfg.min_seconds;
    if (cfg.yescaptcha_key) dom.yescaptchaKey.value = cfg.yescaptcha_key;
    if (typeof cfg.use_proxy === 'boolean') dom.proxyToggle.checked = cfg.use_proxy;
    if (typeof cfg.headless === 'boolean') dom.headlessToggle.checked = cfg.headless;
    if (Array.isArray(cfg.used_accounts) || Array.isArray(cfg.used_mailboxes)) {
      _state.used_accounts = cfg.used_accounts || [];
      _state.used_mailboxes = cfg.used_mailboxes || [];
      renderUsed();
    }
  }

  async function loadConfig() {
    try {
      const cfg = await api('/api/change-email/config');
      applyConfig(cfg);
    } catch (_) { /* tab mới trên server cũ - dùng default */ }
  }

  async function saveConfig() {
    const payload = {
      engine: dom.engine.value,
      candidate: dom.candidate.value || null,
      category: dom.category.value || null,
      captcha_mode: dom.captchaMode.value,
      max_concurrent: parseInt(dom.maxConcurrent.value || '1', 10),
      job_timeout: parseInt(dom.jobTimeout.value || '900', 10),
      poll_timeout_seconds: parseInt(dom.pollTimeout.value || '600', 10),
      min_seconds: parseInt(dom.minSeconds.value || '0', 10),
      yescaptcha_key: dom.yescaptchaKey.value || null,
      use_proxy: dom.proxyToggle.checked,
      headless: dom.headlessToggle.checked,
    };
    try {
      await api('/api/change-email/config', { method: 'POST', body: JSON.stringify(payload) });
    } catch (err) {
      window.GptUi.toast?.(`Lưu config fail: ${err.message}`, { type: 'error' });
    }
  }

  // ── Jobs render ───────────────────────────────────────────────────

  function jobStatusClass(status) {
    if (status === 'success') return 'status-success';
    if (status === 'error') return 'status-error';
    if (status === 'running') return 'status-running';
    if (status === 'queued') return 'status-queued';
    return 'status-cancelled';
  }

  function fmtDuration(j) {
    const start = j.started_at;
    if (!start) return '';
    const end = j.finished_at || (Date.now() / 1000);
    const s = Math.max(0, Math.round(end - start));
    if (s < 60) return `${s}s`;
    return `${Math.floor(s / 60)}m ${s % 60}s`;
  }

  function render() {
    const jobs = _state.jobs || [];
    ensureSelection();
    const counts = jobs.reduce((acc, j) => {
      acc[j.status] = (acc[j.status] || 0) + 1;
      return acc;
    }, {});
    dom.jobSummary.textContent = `${jobs.length} total` +
      (counts.success ? ` · ${counts.success} success` : '') +
      (counts.error ? ` · ${counts.error} error` : '') +
      (counts.running ? ` · ${counts.running} running` : '');

    if (jobs.length === 0) {
      dom.jobList.innerHTML = '<div class="empty">No jobs yet. Điền 2 khung trên và bấm Run Đổi Email.<br><span class="muted">Nếu bị bỏ qua hết: account/mailbox đã dùng → bấm "Xoá lịch sử đã dùng" hoặc nhập account mới.</span></div>';
      return;
    }

    dom.jobList.innerHTML = jobs.map((j) => {
      const fullErr = j.error || '';
      const shortErr = fullErr.length > 140 ? `${fullErr.slice(0, 140)}…` : fullErr;
      const err = fullErr
        ? `<div class="job-detail muted" style="color:var(--red)" title="${escHtml(fullErr)}">${escHtml(shortErr)}</div>`
        : '';
      const sub = j.new_email
        ? `<div class="job-detail muted">→ ${escHtml(j.new_email)}</div>`
        : '';
      const dur = fmtDuration(j);
      return `
        <div class="job change-email-job${j.id === _selectedJobId ? ' selected' : ''}" data-job-id="${escHtml(j.id)}">
          <div class="job-status ${jobStatusClass(j.status)}">${escHtml(j.status)}</div>
          <div class="job-main">
            <div class="job-email" title="${escHtml(j.old_email)}">${escHtml(j.old_email)}</div>
            ${sub}
            ${err}
          </div>
          <div class="job-duration">${escHtml(j.engine)}${dur ? ` · ${dur}` : ''}</div>
          <div class="job-actions">
            <button class="icon-btn" data-action="view-log" data-job-id="${escHtml(j.id)}" title="Xem log">${window.GptUi.icon('list') || '📄'}</button>
            ${j.status === 'queued' || j.status === 'running'
              ? `<button class="icon-btn" data-action="cancel" data-job-id="${escHtml(j.id)}" title="Huỷ job">⏹</button>`
              : ''}
            ${j.status === 'error' || j.status === 'cancelled'
              ? `<button class="icon-btn" data-action="retry" data-job-id="${escHtml(j.id)}" title="Retry">↻</button>`
              : ''}
          </div>
        </div>
      `;
    }).join('');
  }

  function renderLogPane() {
    const job = _state.jobs.find((j) => j.id === _selectedJobId);
    if (!job) {
      dom.logTarget.textContent = '-';
      dom.logPane.textContent = '';
      return;
    }
    dom.logTarget.textContent = `${job.old_email} (${job.status})`;
    fetchLog(job.id);
  }

  function ensureSelection() {
    if (_selectedJobId && _state.jobs.some((j) => j.id === _selectedJobId)) return;
    const running = _state.jobs.find((j) => j.status === 'running' || j.status === 'queued');
    _selectedJobId = (running || _state.jobs[0] || {}).id || null;
    if (_selectedJobId) renderLogPane();
  }

  function parseLogLine(line) {
    const m = /^\[(\d{2}:\d{2}:\d{2})\] (.*)$/.exec(line || '');
    return m ? { time: m[1], msg: m[2] } : { time: '', msg: line || '' };
  }

  function logEntryHtml(job, line) {
    const { time, msg } = parseLogLine(line);
    const err = msg.startsWith('✗');
    return `
      <div class="ev-log-entry${err ? ' err' : ''}">
        <div class="ev-log-head">● ${escHtml(job.old_email)}<span class="ev-log-time">${time}</span></div>
        <div class="ev-log-msg">${escHtml(msg)}</div>
      </div>`;
  }

  function renderLogLines(job, lines) {
    if (!lines.length) {
      dom.logPane.textContent = '(no log yet)';
      return;
    }
    dom.logPane.innerHTML = lines.map((l) => logEntryHtml(job, l)).join('');
    dom.logPane.scrollTop = dom.logPane.scrollHeight;
  }

  async function fetchLog(jobId) {
    const job = _state.jobs.find((j) => j.id === jobId);
    if (!job) return;
    try {
      const data = await api(`/api/change-email/jobs/${jobId}`);
      renderLogLines(job, data.log_lines || []);
    } catch (_) { /* job đã bị xoá */ }
  }

  function applyJobUpdate(update) {
    const idx = _state.jobs.findIndex((j) => j.id === update.id);
    if (idx === -1) {
      _state.jobs.push(update);
    } else {
      _state.jobs[idx] = { ..._state.jobs[idx], ...update };
    }
    scheduleRender();
    if (_selectedJobId === update.id) renderLogPane();
    scheduleRefreshOutputs();
    scheduleRefreshHistory();
  }

  // ── Debounce render/outputs — 1000+ jobs không làm UI freeze ────────
  // Mỗi job event (SSE) sẽ trigger render lại toàn bộ list; bắn 1000 event
  // liên tục = 1000 lần rebuild DOM → gom lại 1 lần sau mỗi 150ms.
  let _renderTimer = null;
  let _outputsTimer = null;
  let _historyTimer = null;

  function scheduleRender() {
    if (_renderTimer) return;
    _renderTimer = setTimeout(() => {
      _renderTimer = null;
      render();
    }, 150);
  }

  function scheduleRefreshOutputs() {
    if (_outputsTimer) return;
    _outputsTimer = setTimeout(() => {
      _outputsTimer = null;
      refreshOutputs();
    }, 400);
  }

  function scheduleRefreshHistory() {
    if (_historyTimer) return;
    _historyTimer = setTimeout(() => {
      _historyTimer = null;
      refreshHistory();
    }, 600);
  }

  function flushPending() {
    if (_renderTimer) { clearTimeout(_renderTimer); _renderTimer = null; render(); }
    if (_outputsTimer) { clearTimeout(_outputsTimer); _outputsTimer = null; refreshOutputs(); }
    if (_historyTimer) { clearTimeout(_historyTimer); _historyTimer = null; refreshHistory(); }
  }

  // ── History (acc đã chạy từ trước, lưu DB) ──────────────────────────

  function historyStatusClass(status) {
    if (status === 'success') return 'status-success';
    if (status === 'error') return 'status-error';
    if (status === 'running') return 'status-running';
    return 'status-cancelled';
  }

  function fmtHistoryTime(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    const p = (n) => String(n).padStart(2, '0');
    return `${p(d.getDate())}/${p(d.getMonth() + 1)} ${p(d.getHours())}:${p(d.getMinutes())}`;
  }

  function renderHistory(list) {
    const items = list || [];
    dom.toggleHistory.textContent = `Lịch sử (${items.length})`;
    if (!items.length) {
      dom.historyList.innerHTML = '<div class="empty">Chưa có lịch sử.</div>';
      return;
    }
    dom.historyList.innerHTML = items.map((h) => {
      const err = h.error
        ? `<div class="job-detail muted" style="color:var(--red)" title="${escHtml(h.error)}">${escHtml(String(h.error).slice(0, 120))}</div>`
        : '';
      return `
        <div class="ce-history-row">
          <div class="job-status ${historyStatusClass(h.status)}">${escHtml(h.status)}</div>
          <div class="ce-history-main">
            <div class="ce-history-emails" title="${escHtml(h.old_email)} → ${escHtml(h.new_email)}">
              ${escHtml(h.old_email)} → ${escHtml(h.new_email)}
            </div>
            ${err}
          </div>
          <div class="ce-history-time muted">${fmtHistoryTime(h.updated_at)}</div>
        </div>`;
    }).join('');
  }

  async function refreshHistory() {
    try {
      const data = await api('/api/change-email/history');
      _state.history = data.history || [];
      if (!dom.historyList.hidden) renderHistory(_state.history);
      dom.toggleHistory.textContent = `Lịch sử (${(_state.history || []).length})`;
    } catch (_) { /* server cũ chưa có route */ }
  }

  function toggleHistory() {
    if (dom.historyList.hidden) {
      dom.historyList.hidden = false;
      renderHistory(_state.history || []);
    } else {
      dom.historyList.hidden = true;
    }
  }

  // ── Actions ───────────────────────────────────────────────────────

  async function run() {
    const accounts = dom.accountInput.value;
    const mailboxes = dom.mailboxInput.value;
    if (!accounts.trim() || !mailboxes.trim()) {
      await Dialog.alert({ message: 'Điền cả 2 khung: tài khoản 1Zone + mailbox mới.' });
      return;
    }
    await saveConfig();
    dom.btnRun.disabled = true;
    dom.btnRun.textContent = 'Đang thêm job...';
    try {
      const res = await api('/api/change-email/jobs', {
        method: 'POST',
        body: JSON.stringify({ accounts, mailboxes }),
      });
      // Merge jobs từ response — đảm bảo list đủ 1000 job kể cả khi SSE
      // drop event lúc bắn burst (queue 1000).
      if (Array.isArray(res.jobs)) {
        const known = new Set(_state.jobs.map((j) => j.id));
        for (const j of res.jobs) {
          if (!known.has(j.id)) _state.jobs.push(j);
        }
        flushPending();
      }
      window.GptUi.toast?.(`Đã thêm ${res.added} job vào queue`, { type: 'success' });
      let note = `Đã thêm ${res.added}`;
      if (res.skipped && res.skipped.length) {
        note += ` · Bỏ qua ${res.skipped.length}`;
        window.GptUi.toast?.(
          `Bỏ qua ${res.skipped.length}: ${res.skipped.slice(0, 5).join('; ')}`,
          { type: 'warning' },
        );
      }
      // Hiển thị bền vững (toast chỉ 2.6s) — user thấy ngay lý do "0 job".
      if (dom.runNote) {
        dom.runNote.textContent = note;
        if (res.skipped && res.skipped.length) {
          dom.runNote.title = res.skipped.join('\n');
        }
      }
    } catch (err) {
      window.GptUi.toast?.(err.message, { type: 'error' });
    } finally {
      dom.btnRun.disabled = false;
      dom.btnRun.textContent = 'Run Đổi Email';
    }
  }

  async function stopAll() {
    try {
      const res = await api('/api/change-email/jobs/stop-all', { method: 'POST' });
      window.GptUi.toast?.(`Đã stop ${res.stopped} job`, { type: 'success' });
    } catch (err) {
      window.GptUi.toast?.(err.message, { type: 'error' });
    }
  }

  async function retryFailed() {
    try {
      const res = await api('/api/change-email/jobs/retry-failed', { method: 'POST' });
      window.GptUi.toast?.(`Retry ${res.retried} job`, { type: 'success' });
    } catch (err) {
      window.GptUi.toast?.(err.message, { type: 'error' });
    }
  }

  async function clearDone() {
    try {
      await api('/api/change-email/jobs/clear-finished', { method: 'POST' });
    } catch (err) {
      window.GptUi.toast?.(err.message, { type: 'error' });
    }
  }

  async function clearAll() {
    try {
      await api('/api/change-email/jobs/clear-all', { method: 'POST' });
    } catch (err) {
      window.GptUi.toast?.(err.message, { type: 'error' });
    }
  }

  async function clearUsed() {
    try {
      const res = await api('/api/change-email/used/clear', { method: 'POST' });
      _state.used_accounts = [];
      _state.used_mailboxes = [];
      renderUsed();
      window.GptUi.toast?.(`Đã xoá ${res.cleared} mục đã dùng`, { type: 'success' });
    } catch (err) {
      window.GptUi.toast?.(err.message, { type: 'error' });
    }
  }

  // ── Output panes ──────────────────────────────────────────────────

  async function refreshOutputs() {
    try {
      const data = await api('/api/change-email/outputs');
      const successLines = data.success || [];
      const errorLines = data.errors || [];
      dom.successPane.textContent = successLines.length
        ? successLines.join('\n')
        : 'Format: mailcu|mailmoi|pass';
      dom.errorPane.textContent = errorLines.length
        ? errorLines.join('\n')
        : 'No errors yet.';
      // Sync danh sách đã dùng (kể cả mailbox bị chặn vừa được mark)
      if (Array.isArray(data.used_accounts) || Array.isArray(data.used_mailboxes)) {
        if (Array.isArray(data.used_accounts)) _state.used_accounts = data.used_accounts;
        if (Array.isArray(data.used_mailboxes)) _state.used_mailboxes = data.used_mailboxes;
        renderUsed();
      }
    } catch (_) { /* server cũ chưa có route */ }
  }

  function copyText(text) {
    navigator.clipboard.writeText(text).then(() => {
      window.GptUi.toast?.('Đã copy', { type: 'success' });
    }).catch(() => {
      window.GptUi.toast?.('Copy fail', { type: 'error' });
    });
  }

  async function retryOne(jobId) {
    try {
      await api(`/api/change-email/jobs/${jobId}/retry`, { method: 'POST' });
      window.GptUi.toast?.('Đã requeue job', { type: 'success' });
    } catch (err) {
      window.GptUi.toast?.(err.message, { type: 'error' });
    }
  }

  async function cancelOne(jobId) {
    try {
      const res = await api(`/api/change-email/jobs/${jobId}/cancel`, { method: 'POST' });
      window.GptUi.toast?.(res.ok ? 'Đã huỷ job' : 'Không thể huỷ (job đã kết thúc)', { type: 'success' });
    } catch (err) {
      window.GptUi.toast?.(err.message, { type: 'error' });
    }
  }

  // ── Events ────────────────────────────────────────────────────────

  function bind() {
    dom.accountInput.addEventListener('input', () => {
      updateCounts();
      persist();
    });
    dom.mailboxInput.addEventListener('input', () => {
      updateCounts();
      persist();
    });
    ['engine', 'candidate', 'category', 'captchaMode', 'maxConcurrent',
     'jobTimeout', 'pollTimeout', 'minSeconds', 'yescaptchaKey',
     'proxyToggle', 'headlessToggle'].forEach((key) => {
      if (dom[key]) dom[key].addEventListener('change', saveConfig);
    });
    dom.btnRun.addEventListener('click', run);
    dom.btnStopAll.addEventListener('click', stopAll);
    dom.btnRetryFailed.addEventListener('click', retryFailed);
    dom.btnClearDone.addEventListener('click', clearDone);
    dom.btnClearAll.addEventListener('click', clearAll);
    dom.btnClearUsed.addEventListener('click', clearUsed);
    dom.toggleHistory.addEventListener('click', toggleHistory);
    dom.btnCopySuccess.addEventListener('click', () => copyText(dom.successPane.textContent));
    dom.btnCopyError.addEventListener('click', () => copyText(dom.errorPane.textContent));
    dom.btnClearInput.addEventListener('click', () => {
      dom.accountInput.value = '';
      dom.mailboxInput.value = '';
      updateCounts();
      persist();
      if (window.GptUi.clearPersistedTextarea) {
        window.GptUi.clearPersistedTextarea(LS_ACCOUNTS_CE);
        window.GptUi.clearPersistedTextarea(LS_MAILBOXES_CE);
      }
    });
    dom.jobList.addEventListener('click', (e) => {
      const row = e.target.closest('[data-job-id]');
      const btn = e.target.closest('[data-action]');
      if (btn) {
        const jobId = btn.dataset.jobId;
        if (btn.dataset.action === 'view-log') {
          _selectedJobId = jobId;
          renderLogPane();
        } else if (btn.dataset.action === 'retry') {
          retryOne(jobId);
        } else if (btn.dataset.action === 'cancel') {
          cancelOne(jobId);
        }
      } else if (row) {
        _selectedJobId = row.dataset.jobId;
        renderLogPane();
      }
    });
  }

  // ── SSE ───────────────────────────────────────────────────────────

  window.SseBus.on('change_email', (data) => {
    if (data.type === 'snapshot') {
      _state.jobs = data.jobs || [];
      applyConfig(data);
      render();
      if (_selectedJobId) renderLogPane();
      refreshOutputs();
    } else if (data.type === 'job') {
      applyJobUpdate(data.job);
    } else if (data.type === 'log' && _selectedJobId === data.job_id) {
      const job = _state.jobs.find((j) => j.id === data.job_id);
      if (job) {
        dom.logTarget.textContent = `${job.old_email} (${job.status})`;
        if (dom.logPane.querySelector('.ev-log-entry')) {
          dom.logPane.insertAdjacentHTML('beforeend', logEntryHtml(job, data.line));
        } else {
          dom.logPane.innerHTML = logEntryHtml(job, data.line);
        }
        dom.logPane.scrollTop = dom.logPane.scrollHeight;
      }
    }
  });

  // ── Init ──────────────────────────────────────────────────────────

  loadPersisted();
  updateCounts();
  bind();
  loadConfig();
  refreshHistory();
  api('/api/change-email/jobs').then((data) => {
    _state.jobs = data.jobs || [];
    applyConfig(data);
    render();
    refreshOutputs();
  }).catch(() => { /* server cũ chưa có route */ });
})();