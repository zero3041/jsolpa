"""UI check: Log pane của tab Đổi Email chỉ cao 1 dòng (không che nút khác).

Inject 3 log entry giả (giống SSE append) rồi đo chiều cao pane + số dòng.
Server phải đang chạy ở 127.0.0.1:8083.
"""
from __future__ import annotations

import sys
import time

sys.path.insert(0, ".")

BASE = "http://127.0.0.1:8083"


def main() -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 900})
        page.goto(BASE, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector('.tab-btn[data-tab="change-email"]', timeout=15000)
        page.click('.tab-btn[data-tab="change-email"]')
        time.sleep(1)

        # Inject 3 log entry giả (cùng cấu trúc SSE append)
        page.evaluate(
            """() => {
                const pane = document.getElementById('ce-log-pane');
                const entry = (cls, msg) => {
                    const div = document.createElement('div');
                    div.className = 'ev-log-entry' + (cls ? ' ' + cls : '');
                    div.innerHTML = '<div class="ev-log-head">● x@y.com<span class="ev-log-time">12:00:00</span></div>'
                        + '<div class="ev-log-msg">' + msg + '</div>';
                    return div;
                };
                pane.appendChild(entry('', '● Bắt đầu job'));
                pane.appendChild(entry('', '● Dùng proxy http://user:pass@host:8080'));
                pane.appendChild(entry('err', '✗ không mở được dialog Đăng nhập: Timeout'));
            }"""
        )

        time.sleep(0.5)
        pane_h = page.evaluate(
            "() => { const p = document.getElementById('ce-log-pane'); "
            "return Math.round(p.getBoundingClientRect().height); }"
        )
        msg_lines = page.evaluate(
            "() => { const es = [...document.querySelectorAll('#ce-log-pane .ev-log-msg')]; "
            "return es.map(e => Math.round(e.getBoundingClientRect().height)); }"
        )
        head_visible = page.evaluate(
            "() => { const h = document.querySelector('#ce-log-pane .ev-log-head'); "
            "return h ? getComputedStyle(h).display : 'none'; }"
        )
        err_style = page.evaluate(
            "() => { const e = document.querySelector('#ce-log-pane .ev-log-entry.err .ev-log-msg'); "
            "return e ? getComputedStyle(e).whiteSpace : ''; }"
        )

        print(f"pane height: {pane_h}px (target <= 30)", flush=True)
        print(f"msg line heights: {msg_lines} (target ~1 dòng)", flush=True)
        print(f"head display: {head_visible} (target none)", flush=True)
        print(f"msg white-space: {err_style} (target nowrap)", flush=True)

        browser.close()

        ok = pane_h <= 30 and head_visible == "none" and err_style == "nowrap"
        print("LOG SIZE CHECK " + ("PASS" if ok else "FAIL"), flush=True)
        if not ok:
            raise SystemExit(1)


if __name__ == "__main__":
    main()