/* gpt_signup_hybrid — Đọc Hòm Thư tab logic (Mail Reader).
 *
 * Nhập combo `email|password|refresh_token|client_id` → check từng account:
 *   alive         = refresh token OK + đọc được thư (kèm danh sách thư mới nhất)
 *   dead          = token lỗi vĩnh viễn (invalid_grant / expired / disabled)
 *   network_error = không kết luận được (lỗi mạng)
 */
(function () {
  'use strict';

  if (document.querySelector('.tab-btn[data-tab="mailread"]') === null) return;

  const LS_INPUT_MR = 'gpt_reg.mail_reader_input';
  const LS_MAX_MSGS = 'gpt_reg.mail_reader_max_messages';

  const dom = {
    input: document.getElementById('mr-combo-input'),
    maxMessages: document.getElementById('mr-max-messages'),
    btnCheck: document.getElementById('mr-btn-check'),
    btnClear: document.getElementById('mr-btn-clear-input'),
    btnCopyAlive: document.getElementById('mr-btn-copy-alive'),
    btnCopyDead: document.getElementById('mr-btn-copy-dead'),
    comboCount: document.getElementById('mr-combo-count'),
    summary: document.getElementById('mr-summary'),
    resultList: document.getElementById('mr-result-list'),
    mailTarget: document.getElementById('mr-mail-target'),
    mailPane: document.getElementById('mr-mail-pane'),
  };

  let _lastResult = null;

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

  function fmtReceived(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso);
    return d.toLocaleString('vi-VN', {
      day: '2-digit', month: '2-digit', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  }

  function updateComboCount() {
    const lines = dom.input.value.split('\n').filter((l) => {
      const s = l.trim();
      return s && !s.startsWith('#');
    });
    dom.comboCount.textContent = `${lines.length} dòng`;
  }

  function persist() {
    if (window.GptUi.persistTextarea) {
      window.GptUi.persistTextarea(LS_INPUT_MR, dom.input.value);
    }
  }

  function loadPersisted() {
    try {
      const saved = localStorage.getItem(LS_INPUT_MR);
      if (saved !== null) dom.input.value = saved;
    } catch (_) { /* ignore */ }
    if (window.Settings && window.Settings.get) {
      const savedMax = window.Settings.get(LS_MAX_MSGS);
      if (savedMax && /^\d+$/.test(String(savedMax))) {
        dom.maxMessages.value = String(Math.max(1, Math.min(50, parseInt(savedMax, 10))));
      }
    }
  }

  function renderResults(data) {
    _lastResult = data;
    const results = data.results || [];

    dom.summary.textContent = [
      `${data.total} total`,
      data.alive ? `${data.alive} alive` : '',
      data.dead ? `${data.dead} dead` : '',
      data.network_error ? `${data.network_error} network_error` : '',
    ].filter(Boolean).join(' · ') || '-';

    if (data.parse_error) {
      dom.resultList.innerHTML = `<div class="empty" style="color:var(--red)">${escHtml(data.parse_error)}</div>`;
      return;
    }

    if (results.length === 0) {
      dom.resultList.innerHTML = '<div class="empty">Không có combo nào.</div>';
      return;
    }

    const html = results.map((r, idx) => {
      const err = r.error ? `<div class="job-detail muted" style="color:var(--red)">${escHtml(r.error)}</div>` : '';
      const mailCount = r.status === 'alive'
        ? `<span class="job-duration">${r.message_count} thư</span>`
        : '<span class="job-duration">-</span>';
      const viewBtn = r.status === 'alive' && r.messages.length > 0
        ? `<button class="icon-btn" data-action="view-mail" data-idx="${idx}" title="Xem thư">${window.GptUi.icon('link') || '📄'}</button>`
        : '';
      return `
        <div class="job" data-idx="${idx}">
          <div class="job-index">${idx + 1}</div>
          <div class="job-status status-${r.status}">${escHtml(r.status)}</div>
          <div class="job-main">
            <div class="job-email" title="${escHtml(r.email)}">${escHtml(r.email)}</div>
            ${err}
          </div>
          ${mailCount}
          <div class="job-actions">${viewBtn}</div>
        </div>
      `;
    }).join('');

    dom.resultList.innerHTML = html;
  }

  function renderMails(idx) {
    if (!_lastResult || !_lastResult.results) return;
    const r = _lastResult.results[idx];
    if (!r || r.status !== 'alive') return;
    dom.mailTarget.textContent = r.email;
    if (r.messages.length === 0) {
      dom.mailPane.textContent = 'Hòm thư trống (không có thư).';
      return;
    }
    const lines = r.messages.map((m, i) => {
      const read = m.is_read ? '' : ' (UNREAD)';
      return [
        `── ${i + 1}. ${m.subject}${read}`,
        `    from:     ${m.from || '-'}`,
        `    received: ${m.received || '-'}  (${fmtReceived(m.received)})`,
        `    preview:  ${m.preview || '(không có preview)'}`,
      ].join('\n');
    });
    dom.mailPane.textContent = lines.join('\n\n');
  }

  function saveMaxMessages(max) {
    if (window.Settings && window.Settings.save) {
      // Lưu int (không phải string) — Settings Store validate int trong [1, 50].
      window.Settings.save(LS_MAX_MSGS, max, window.GptUi.getAuthToken());
    }
  }

  async function runCheck() {
    const combos = dom.input.value;
    if (!combos.trim()) {
      await Dialog.alert({ message: 'Dán combo trước khi bấm Đọc Mail.' });
      return;
    }
    const max = Math.max(1, Math.min(50, parseInt(dom.maxMessages.value || '10', 10) || 10));
    dom.maxMessages.value = String(max);
    saveMaxMessages(max);

    dom.btnCheck.disabled = true;
    dom.btnCheck.textContent = 'Đang check...';
    dom.summary.textContent = 'checking...';
    dom.resultList.innerHTML = '<div class="empty">Đang refresh token + đọc thư... (mỗi account 1-2s)</div>';

    try {
      const data = await api('/api/mail-reader/check', {
        method: 'POST',
        body: JSON.stringify({ combos, max_messages: max }),
      });
      renderResults(data);
      if (data.alive === 0 && data.total > 0) {
        window.GptUi.playErrorAlert?.();
      }
    } catch (err) {
      dom.resultList.innerHTML = `<div class="empty" style="color:var(--red)">${escHtml(err.message)}</div>`;
      window.GptUi.toast?.(err.message, { type: 'error' });
    } finally {
      dom.btnCheck.disabled = false;
      dom.btnCheck.textContent = 'Đọc Mail';
    }
  }

  function copyAlive() {
    if (!_lastResult || !_lastResult.results) return;
    const lines = _lastResult.results
      .filter((r) => r.status === 'alive')
      .map((r) => r.email);
    window.GptUi.copyWithToast(lines.join('\n') || '(không có account alive)', 'Đã copy alive list');
  }

  function copyDead() {
    if (!_lastResult || !_lastResult.results) return;
    const lines = _lastResult.results
      .filter((r) => r.status === 'dead' || r.status === 'network_error')
      .map((r) => r.email);
    window.GptUi.copyWithToast(lines.join('\n') || '(không có account chết)', 'Đã copy dead list');
  }

  function bind() {
    dom.input.addEventListener('input', () => {
      updateComboCount();
      persist();
    });
    dom.maxMessages.addEventListener('change', () => {
      const max = Math.max(1, Math.min(50, parseInt(dom.maxMessages.value || '10', 10) || 10));
      dom.maxMessages.value = String(max);
      saveMaxMessages(max);
    });
    dom.btnCheck.addEventListener('click', runCheck);
    dom.btnClear.addEventListener('click', () => {
      dom.input.value = '';
      updateComboCount();
      persist();
      if (window.GptUi.clearPersistedTextarea) {
        window.GptUi.clearPersistedTextarea(LS_INPUT_MR);
      }
      dom.resultList.innerHTML = '<div class="empty">Dán combo và bấm "Đọc Mail" để check account còn sống không.</div>';
      dom.mailPane.textContent = '';
      dom.mailTarget.textContent = '-';
      dom.summary.textContent = '-';
      _lastResult = null;
    });
    dom.btnCopyAlive.addEventListener('click', copyAlive);
    dom.btnCopyDead.addEventListener('click', copyDead);
    dom.resultList.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-action="view-mail"]');
      if (!btn) return;
      renderMails(parseInt(btn.dataset.idx, 10));
    });
  }

  loadPersisted();
  updateComboCount();
  bind();
})();