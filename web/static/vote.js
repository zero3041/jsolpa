/* gpt_signup_hybrid - Auto Vote tab logic.
 *
 * Dán combo `email|password` (tài khoản 1Zone) → login trên
 * tinhhasayhi.1vote.vn → bình chọn candidate → xem video 30s →
 * (dry-run mặc định: dừng khi nút "Bình chọn ngay" sẵn sàng).
 */
(function () {
  'use strict';

  if (document.querySelector('.tab-btn[data-tab="vote"]') === null) return;

  const LS_INPUT_VT = 'gpt_reg.vote_input';

  const dom = {
    input: document.getElementById('vt-combo-input'),
    engine: document.getElementById('vt-engine'),
    candidate: document.getElementById('vt-candidate'),
    category: document.getElementById('vt-category'),
    maxConcurrent: document.getElementById('vt-max-concurrent'),
    jobTimeout: document.getElementById('vt-job-timeout'),
    minSeconds: document.getElementById('vt-min-seconds'),
    proxyToggle: document.getElementById('vt-proxy-toggle'),
    headlessToggle: document.getElementById('vt-headless-toggle'),
    confirmToggle: document.getElementById('vt-confirm-toggle'),
    btnRun: document.getElementById('vt-btn-run'),
    btnStopAll: document.getElementById('vt-btn-stop-all'),
    btnClearInput: document.getElementById('vt-btn-clear-input'),
    btnRetryFailed: document.getElementById('vt-btn-retry-failed'),
    btnClearDone: document.getElementById('vt-btn-clear-done'),
    btnClearAll: document.getElementById('vt-btn-clear-all'),
    btnCopySuccess: document.getElementById('vt-btn-copy-success'),
    btnCopyError: document.getElementById('vt-btn-copy-error'),
    comboCount: document.getElementById('vt-combo-count'),
    jobSummary: document.getElementById('vt-job-summary'),
    jobList: document.getElementById('vt-job-list'),
    successPane: document.getElementById('vt-success-pane'),
    errorPane: document.getElementById('vt-error-pane'),
    logTarget: document.getElementById('vt-log-target'),
    logPane: document.getElementById('vt-log-pane'),
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
      window.GptUi.persistTextarea(LS_INPUT_VT, dom.input.value);
    }
  }

  function loadPersisted() {
    try {
      const saved = localStorage.getItem(LS_INPUT_VT);
      if (saved !== null) dom.input.value = saved;
    } catch (_) { /* ignore */ }
  }

  // ── Config load/save ─────────────────────────────────────────────

  function applyConfig(cfg) {
    if (!cfg) return;
    if (cfg.engine && dom.engine.querySelector(`option[value="${cfg.engine}"]`)) {
      dom.engine.value = cfg.engine;
    }
    if (cfg.candidate) dom.candidate.value = cfg.candidate;
    if (typeof cfg.category === 'string') dom.category.value = cfg.category;
    if (cfg.max_concurrent) dom.maxConcurrent.value = cfg.max_concurrent;
    if (cfg.job_timeout) dom.jobTimeout.value = cfg.job_timeout;
    if (typeof cfg.min_seconds === 'number') dom.minSeconds.value = cfg.min_seconds;
    if (typeof cfg.use_proxy === 'boolean') dom.proxyToggle.checked = cfg.use_proxy;
    if (typeof cfg.headless === 'boolean') dom.headlessToggle.checked = cfg.headless;
    if (typeof cfg.confirm_vote === 'boolean') dom.confirmToggle.checked = cfg.confirm_vote;
  }

  async function loadConfig() {
    try {
      const cfg = await api('/api/vote/config');
      applyConfig(cfg);
    } catch (_) { /* tab mới trên server cũ - dùng default */ }
  }

  async function saveConfig() {
    const payload = {
      engine: dom.engine.value,
      candidate: dom.candidate.value || null,
      category: dom.category.value || '',
      max_concurrent: parseInt(dom.maxConcurrent.value || '1', 10),
      job_timeout: parseInt(dom.jobTimeout.value || '600', 10),
      min_seconds: parseInt(dom.minSeconds.value || '60', 10),
      use_proxy: dom.proxyToggle.checked,
      headless: dom.headlessToggle.checked,
      confirm_vote: dom.confirmToggle.checked,
    };
    try {
      await api('/api/vote/config', { method: 'POST', body: JSON.stringify(payload) });
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
      dom.jobList.innerHTML = '<div class="empty">No jobs yet. Paste combos và bấm Run Vote.</div>';
      return;
    }

    dom.jobList.innerHTML = jobs.map((j) => {
      const fullErr = j.error || '';
      const shortErr = fullErr.length > 140 ? `${fullErr.slice(0, 140)}…` : fullErr;
      const err = fullErr
        ? `<div class="job-detail muted" style="color:var(--red)" title="${escHtml(fullErr)}">${escHtml(shortErr)}</div>`
        : '';
      const vr = j.vote_result;
      const voteLine = vr
        ? `<div class="job-detail muted" title="${escHtml(JSON.stringify(vr))}">` +
          `Vote: ${escHtml(vr.product || '?')} +${escHtml(vr.point ?? 0)}đ` +
          (vr.total_point != null ? ` · tổng ${escHtml(vr.total_point)}` : '') +
          (vr.remaining_free_votes != null ? ` · còn ${escHtml(vr.remaining_free_votes)} lượt free` : '') +
          (vr.next_vote_in_seconds != null ? ` · sau ${escHtml(vr.next_vote_in_seconds)}s` : '') +
          `</div>`
        : '';
      const dur = fmtDuration(j);
      return `
        <div class="job vote-job${j.id === _selectedJobId ? ' selected' : ''}" data-job-id="${escHtml(j.id)}">
          <div class="job-status ${jobStatusClass(j.status)}">${escHtml(j.status)}</div>
          <div class="job-main">
            <div class="job-email" title="${escHtml(j.email)}">${escHtml(j.email)}</div>
            ${voteLine}
            ${err}
          </div>
          <div class="job-duration">${escHtml(j.engine)}${dur ? ` · ${dur}` : ''}</div>
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
      const data = await api(`/api/vote/jobs/${jobId}`);
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
      await api('/api/vote/jobs', { method: 'POST', body: JSON.stringify({ combos }) });
      window.GptUi.toast?.('Jobs đã được thêm vào queue', { type: 'success' });
    } catch (err) {
      window.GptUi.toast?.(err.message, { type: 'error' });
    } finally {
      dom.btnRun.disabled = false;
      dom.btnRun.textContent = 'Run Vote';
    }
  }

  async function stopAll() {
    try {
      const res = await api('/api/vote/jobs/stop-all', { method: 'POST' });
      window.GptUi.toast?.(`Đã stop ${res.stopped} job`, { type: 'success' });
    } catch (err) {
      window.GptUi.toast?.(err.message, { type: 'error' });
    }
  }

  async function retryFailed() {
    try {
      const res = await api('/api/vote/jobs/retry-failed', { method: 'POST' });
      window.GptUi.toast?.(`Retry ${res.retried} job`, { type: 'success' });
    } catch (err) {
      window.GptUi.toast?.(err.message, { type: 'error' });
    }
  }

  async function clearDone() {
    try {
      await api('/api/vote/jobs/clear-finished', { method: 'POST' });
    } catch (err) {
      window.GptUi.toast?.(err.message, { type: 'error' });
    }
  }

  async function clearAll() {
    try {
      await api('/api/vote/jobs/clear-all', { method: 'POST' });
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
        successLines.push(`${j.email}|${j.password || ''}`);
      } else if (j.status === 'error') {
        errorLines.push(`${j.email}  →  ${j.error || 'unknown'}`);
      }
    }
    dom.successPane.textContent = successLines.length
      ? successLines.join('\n')
      : 'Format: email|password|ip';
    dom.errorPane.textContent = errorLines.length
      ? errorLines.join('\n')
      : 'No errors yet.';
  }

  async function refreshOutputs() {
    try {
      const data = await api('/api/vote/outputs');
      const successLines = data.success || [];
      const errorLines = data.errors || [];
      dom.successPane.textContent = successLines.length
        ? successLines.join('\n')
        : 'Format: email|password|ip';
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

  async function retryOne(jobId) {
    try {
      await api(`/api/vote/jobs/${jobId}/retry`, { method: 'POST' });
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
    ['engine', 'candidate', 'category', 'maxConcurrent', 'jobTimeout', 'minSeconds',
     'proxyToggle', 'headlessToggle', 'confirmToggle'].forEach((key) => {
      dom[key].addEventListener('change', saveConfig);
    });
    dom.btnRun.addEventListener('click', run);
    dom.btnStopAll.addEventListener('click', stopAll);
    dom.btnRetryFailed.addEventListener('click', retryFailed);
    dom.btnClearDone.addEventListener('click', clearDone);
    dom.btnClearAll.addEventListener('click', clearAll);
    dom.btnCopySuccess.addEventListener('click', () => copyText(dom.successPane.textContent));
    dom.btnCopyError.addEventListener('click', () => copyText(dom.errorPane.textContent));
    dom.btnClearInput.addEventListener('click', () => {
      dom.input.value = '';
      updateComboCount();
      persist();
      if (window.GptUi.clearPersistedTextarea) {
        window.GptUi.clearPersistedTextarea(LS_INPUT_VT);
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

  window.SseBus.on('vote', (data) => {
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
  api('/api/vote/jobs').then((data) => {
    _state.jobs = data.jobs || [];
    applyConfig(data);
    render();
    refreshOutputs();
  }).catch(() => { /* server cũ chưa có route */ });
})();
