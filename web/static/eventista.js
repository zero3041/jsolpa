/* gpt_signup_hybrid - Reg Eventista tab logic.
 *
 * Dán combo `email|password|refresh_token|client_id` → đăng ký tự động trên
 * tinhhasayhi.1vote.vn (browser engine cấu hình được), poll mail Outlook qua
 * Graph API lấy link kích hoạt verify-email và mở link.
 */
(function () {
  'use strict';

  if (document.querySelector('.tab-btn[data-tab="eventista"]') === null) return;

  const LS_INPUT_EV = 'gpt_reg.eventista_input';

  const dom = {
    input: document.getElementById('ev-combo-input'),
    engine: document.getElementById('ev-engine'),
    captchaMode: document.getElementById('ev-captcha-mode'),
    maxConcurrent: document.getElementById('ev-max-concurrent'),
    defaultPassword: document.getElementById('ev-default-password'),
    pollTimeout: document.getElementById('ev-poll-timeout'),
    jobTimeout: document.getElementById('ev-job-timeout'),
    yescaptchaKey: document.getElementById('ev-yescaptcha-key'),
    proxyToggle: document.getElementById('ev-proxy-toggle'),
    headlessToggle: document.getElementById('ev-headless-toggle'),
    btnRun: document.getElementById('ev-btn-run'),
    btnStopAll: document.getElementById('ev-btn-stop-all'),
    btnClearInput: document.getElementById('ev-btn-clear-input'),
    btnPickCombos: document.getElementById('ev-btn-pick-combos'),
    btnRetryFailed: document.getElementById('ev-btn-retry-failed'),
    btnClearDone: document.getElementById('ev-btn-clear-done'),
    btnClearAll: document.getElementById('ev-btn-clear-all'),
    btnScrollJobs: document.getElementById('ev-btn-scroll-jobs'),
    btnCopySuccess: document.getElementById('ev-btn-copy-success'),
    btnCopyError: document.getElementById('ev-btn-copy-error'),
    comboCount: document.getElementById('ev-combo-count'),
    jobSummary: document.getElementById('ev-job-summary'),
    jobList: document.getElementById('ev-job-list'),
    successPane: document.getElementById('ev-success-pane'),
    errorPane: document.getElementById('ev-error-pane'),
    logTarget: document.getElementById('ev-log-target'),
    logPane: document.getElementById('ev-log-pane'),
  };

  let _state = { jobs: [] };
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

  function updateComboCount() {
    const lines = dom.input.value.split('\n').filter((l) => {
      const s = l.trim();
      return s && !s.startsWith('#');
    });
    dom.comboCount.textContent = `${lines.length} combos`;
  }

  function persist() {
    if (window.GptUi.persistTextarea) {
      window.GptUi.persistTextarea(LS_INPUT_EV, dom.input.value);
    }
  }

  function loadPersisted() {
    try {
      const saved = localStorage.getItem(LS_INPUT_EV);
      if (saved !== null) dom.input.value = saved;
    } catch (_) { /* ignore */ }
  }

  // ── Config load/save ─────────────────────────────────────────────

  function applyConfig(cfg) {
    if (!cfg) return;
    if (cfg.engine && dom.engine.querySelector(`option[value="${cfg.engine}"]`)) {
      dom.engine.value = cfg.engine;
    }
    if (cfg.captcha_mode) dom.captchaMode.value = cfg.captcha_mode;
    if (cfg.max_concurrent) dom.maxConcurrent.value = cfg.max_concurrent;
    if (typeof cfg.default_password === 'string') dom.defaultPassword.value = cfg.default_password;
    if (cfg.poll_timeout_seconds) dom.pollTimeout.value = cfg.poll_timeout_seconds;
    if (cfg.job_timeout) dom.jobTimeout.value = cfg.job_timeout;
    if (cfg.yescaptcha_key) dom.yescaptchaKey.value = cfg.yescaptcha_key;
    if (typeof cfg.use_proxy === 'boolean') dom.proxyToggle.checked = cfg.use_proxy;
    if (typeof cfg.headless === 'boolean') dom.headlessToggle.checked = cfg.headless;
  }

  async function loadConfig() {
    try {
      const cfg = await api('/api/eventista/config');
      applyConfig(cfg);
    } catch (_) { /* tab mới trên server cũ - dùng default */ }
  }

  async function saveConfig() {
    const payload = {
      engine: dom.engine.value,
      captcha_mode: dom.captchaMode.value,
      max_concurrent: parseInt(dom.maxConcurrent.value || '1', 10),
      default_password: dom.defaultPassword.value || null,
      poll_timeout_seconds: parseInt(dom.pollTimeout.value || '600', 10),
      job_timeout: parseInt(dom.jobTimeout.value || '600', 10),
      yescaptcha_key: dom.yescaptchaKey.value || null,
      use_proxy: dom.proxyToggle.checked,
      headless: dom.headlessToggle.checked,
    };
    try {
      await api('/api/eventista/config', { method: 'POST', body: JSON.stringify(payload) });
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
      dom.jobList.innerHTML = '<div class="empty">No jobs yet. Paste combos và bấm Run Eventista.</div>';
      return;
    }

    dom.jobList.innerHTML = jobs.map((j) => {
      const fullErr = j.error || '';
      const shortErr = fullErr.length > 140 ? `${fullErr.slice(0, 140)}…` : fullErr;
      const err = fullErr
        ? `<div class="job-detail muted" style="color:var(--red)" title="${escHtml(fullErr)}">${escHtml(shortErr)}</div>`
        : '';
      const activation = j.activation_url
        ? `<div class="job-detail muted">✓ <a href="${escHtml(j.activation_url)}" target="_blank" rel="noopener">activation link</a></div>`
        : '';
      return `
        <div class="job eventista-job${j.id === _selectedJobId ? ' selected' : ''}" data-job-id="${escHtml(j.id)}">
          <div class="job-status ${jobStatusClass(j.status)}">${escHtml(j.status)}</div>
          <div class="job-main">
            <div class="job-email" title="${escHtml(j.email)}">${escHtml(j.email)}</div>
            ${err}${activation}
          </div>
          <div class="job-duration">${escHtml(j.engine)}</div>
          <div class="job-actions">
            <button class="icon-btn" data-action="view-log" data-job-id="${escHtml(j.id)}" title="Xem log">${window.GptUi.icon('list') || '📄'}</button>
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
    dom.logTarget.textContent = `${job.email} (${job.status})`;
    fetchLog(job.id);
  }

  // Tự chọn job để log live hiển thị ngay: ưu tiên job đang chạy, rồi job đầu tiên.
  function ensureSelection() {
    if (_selectedJobId && _state.jobs.some((j) => j.id === _selectedJobId)) return;
    const running = _state.jobs.find((j) => j.status === 'running' || j.status === 'queued');
    _selectedJobId = (running || _state.jobs[0] || {}).id || null;
    if (_selectedJobId) renderLogPane();
  }

  // Parse "[HH:MM:SS] msg" → { time, msg } (backend _job_log format).
  function parseLogLine(line) {
    const m = /^\[(\d{2}:\d{2}:\d{2})\] (.*)$/.exec(line || '');
    return m ? { time: m[1], msg: m[2] } : { time: '', msg: line || '' };
  }

  // Render 1 log entry: ● email / action / time — 3 dòng, đúng ô đúng cột.
  function logEntryHtml(job, line) {
    const { time, msg } = parseLogLine(line);
    const err = msg.startsWith('✗');
    return `
      <div class="ev-log-entry${err ? ' err' : ''}">
        <div class="ev-log-head">● ${escHtml(job.email)}<span class="ev-log-time">${time}</span></div>
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
      const data = await api(`/api/eventista/jobs/${jobId}`);
      const creds = data.status === 'success' && data.password
        ? `<div class="ev-log-creds">TÀI KHOẢN: ${escHtml(data.email)}<br>MẬT KHẨU: ${escHtml(data.password)}</div>`
        : '';
      dom.logPane.innerHTML = creds + renderLinesInner(job, data.log_lines || []);
      dom.logPane.scrollTop = dom.logPane.scrollHeight;
    } catch (_) { /* job đã bị xoá */ }
  }

  function renderLinesInner(job, lines) {
    if (!lines.length) return '(no log yet)';
    return lines.map((l) => logEntryHtml(job, l)).join('');
  }

  function applyJobUpdate(update) {
    const idx = _state.jobs.findIndex((j) => j.id === update.id);
    if (idx === -1) {
      _state.jobs.push(update);
    } else {
      _state.jobs[idx] = { ..._state.jobs[idx], ...update };
    }
    render();
    if (_selectedJobId === update.id) renderLogPane();
    refreshOutputs();
  }

  // ── Actions ───────────────────────────────────────────────────────

  async function run() {
    const combos = dom.input.value;
    if (!combos.trim()) {
      await Dialog.alert({ message: 'Dán combo trước khi chạy.' });
      return;
    }
    await saveConfig();
    dom.btnRun.disabled = true;
    dom.btnRun.textContent = 'Đang thêm job...';
    try {
      await api('/api/eventista/jobs', { method: 'POST', body: JSON.stringify({ combos }) });
      window.GptUi.toast?.('Jobs đã được thêm vào queue', { type: 'success' });
    } catch (err) {
      window.GptUi.toast?.(err.message, { type: 'error' });
    } finally {
      dom.btnRun.disabled = false;
      dom.btnRun.textContent = 'Run Eventista';
    }
  }

  async function stopAll() {
    try {
      const res = await api('/api/eventista/jobs/stop-all', { method: 'POST' });
      window.GptUi.toast?.(`Đã stop ${res.stopped} job`, { type: 'success' });
    } catch (err) {
      window.GptUi.toast?.(err.message, { type: 'error' });
    }
  }

  async function retryFailed() {
    try {
      const res = await api('/api/eventista/jobs/retry-failed', { method: 'POST' });
      window.GptUi.toast?.(`Retry ${res.retried} job`, { type: 'success' });
    } catch (err) {
      window.GptUi.toast?.(err.message, { type: 'error' });
    }
  }

  async function clearDone() {
    try {
      await api('/api/eventista/jobs/clear-finished', { method: 'POST' });
    } catch (err) {
      window.GptUi.toast?.(err.message, { type: 'error' });
    }
  }

  async function clearAll() {
    try {
      await api('/api/eventista/jobs/clear-all', { method: 'POST' });
    } catch (err) {
      window.GptUi.toast?.(err.message, { type: 'error' });
    }
  }

  // ── Output panes ──────────────────────────────────────────────────

  function renderOutputs() {
    const successLines = [];
    const errorLines = [];
    for (const j of _state.jobs) {
      if (j.status === 'success') {
        successLines.push(`${j.email}|${j.password || ''}|no_2fa`);
      } else if (j.status === 'error') {
        errorLines.push(`${j.email}  →  ${j.error || 'unknown'}`);
      }
    }
    dom.successPane.textContent = successLines.length
      ? successLines.join('\n')
      : 'Format: email|password|secret_2fa';
    dom.errorPane.textContent = errorLines.length
      ? errorLines.join('\n')
      : 'No errors yet.';
  }

  async function refreshOutputs() {
    try {
      const data = await api('/api/eventista/outputs');
      const successLines = data.success || [];
      const errorLines = data.errors || [];
      dom.successPane.textContent = successLines.length
        ? successLines.join('\n')
        : 'Format: email|password|secret_2fa';
      dom.errorPane.textContent = errorLines.length
        ? errorLines.join('\n')
        : 'No errors yet.';
    } catch (_) { /* server cũ chưa có route */ }
  }

  function copyText(text) {
    navigator.clipboard.writeText(text).then(() => {
      window.GptUi.toast?.('Đã copy', { type: 'success' });
    }).catch(() => {
      window.GptUi.toast?.('Copy fail', { type: 'error' });
    });
  }

  async function pickCombos() {
    dom.btnPickCombos.disabled = true;
    try {
      const data = await api('/api/eventista/combos');
      const combos = data.combos || [];
      if (combos.length === 0) {
        window.GptUi.toast?.('Không có combo nào chưa dùng Eventista trong DB', { type: 'info' });
        return;
      }
      const lines = combos.map((c) =>
        `${c.email}|${c.password}|${c.refresh_token}|${c.client_id}`
      );
      const existing = new Set(dom.input.value.split('\n').map((l) => l.trim()).filter(Boolean));
      const merged = [...existing, ...lines.filter((l) => !existing.has(l))];
      dom.input.value = merged.join('\n');
      updateComboCount();
      persist();
      window.GptUi.toast?.(`Đã thêm ${lines.length} combo từ DB`, { type: 'success' });
    } catch (err) {
      window.GptUi.toast?.(err.message, { type: 'error' });
    } finally {
      dom.btnPickCombos.disabled = false;
    }
  }

  async function retryOne(jobId) {
    try {
      await api(`/api/eventista/jobs/${jobId}/retry`, { method: 'POST' });
      window.GptUi.toast?.('Đã requeue job', { type: 'success' });
    } catch (err) {
      window.GptUi.toast?.(err.message, { type: 'error' });
    }
  }

  // ── Events ────────────────────────────────────────────────────────

  function bind() {
    dom.input.addEventListener('input', () => {
      updateComboCount();
      persist();
    });
    ['engine', 'captchaMode', 'maxConcurrent', 'defaultPassword', 'pollTimeout',
     'jobTimeout', 'yescaptchaKey', 'proxyToggle', 'headlessToggle'].forEach((key) => {
      dom[key].addEventListener('change', saveConfig);
    });
    dom.btnRun.addEventListener('click', run);
    dom.btnStopAll.addEventListener('click', stopAll);
    dom.btnRetryFailed.addEventListener('click', retryFailed);
    dom.btnClearDone.addEventListener('click', clearDone);
    dom.btnClearAll.addEventListener('click', clearAll);
    dom.btnScrollJobs.addEventListener('click', () => {
      dom.jobList.scrollTo({ top: dom.jobList.scrollHeight, behavior: 'smooth' });
    });
    dom.btnCopySuccess.addEventListener('click', () => copyText(dom.successPane.textContent));
    dom.btnCopyError.addEventListener('click', () => copyText(dom.errorPane.textContent));
    dom.btnPickCombos.addEventListener('click', pickCombos);
    dom.btnClearInput.addEventListener('click', () => {
      dom.input.value = '';
      updateComboCount();
      persist();
      if (window.GptUi.clearPersistedTextarea) {
        window.GptUi.clearPersistedTextarea(LS_INPUT_EV);
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
        }
      } else if (row) {
        _selectedJobId = row.dataset.jobId;
        renderLogPane();
      }
    });
  }

  // ── SSE ───────────────────────────────────────────────────────────

  window.SseBus.on('eventista', (data) => {
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
        dom.logTarget.textContent = `${job.email} (${job.status})`;
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
  updateComboCount();
  bind();
  loadConfig();
  api('/api/eventista/jobs').then((data) => {
    _state.jobs = data.jobs || [];
    applyConfig(data);
    render();
    refreshOutputs();
  }).catch(() => { /* server cũ chưa có route */ });
})();
