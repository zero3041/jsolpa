"""UI check: bấm Run Đổi Email — có modal/toast/console error không."""
from __future__ import annotations

import sys
import time

sys.path.insert(0, ".")

BASE = "http://127.0.0.1:8083"


def main() -> None:
    from playwright.sync_api import sync_playwright

    console_errors: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 900})
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errors.append(f"PAGEERROR: {e}\n{e.stack or ''}"))

        page.goto(BASE, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector('.tab-btn[data-tab="change-email"]', timeout=15000)
        page.click('.tab-btn[data-tab="change-email"]')
        time.sleep(1)

        # 1. Run với 2 khung rỗng → phải hiện Dialog.alert
        page.click("#ce-btn-run")
        time.sleep(1)
        alert_visible = page.evaluate(
            "() => !!document.querySelector('#hme-feedback-modal.open')"
        )
        print(f"[1] Run với khung rỗng → alert/modal: {alert_visible}", flush=True)

        # Đóng modal bằng nút trong #hme-feedback-actions
        if alert_visible:
            try:
                page.click("#hme-feedback-actions button")
                time.sleep(0.5)
            except Exception:  # noqa: BLE001
                pass

        # 2. Điền account + mailbox rỗng → toast "Đã thêm 0 + bỏ qua"
        page.fill("#ce-account-input", "ngadangmeow+500@outlook.com|Vote@sol")
        page.fill("#ce-mailbox-input", "")
        page.click("#ce-btn-run")
        time.sleep(1.5)
        toast_text = page.evaluate(
            "() => [...document.querySelectorAll('.gpt-toast-msg')].map(e => e.textContent).join(' | ')"
        )
        print(f"[2] toast sau Run (mailbox rỗng): {toast_text!r}", flush=True)
        run_note = page.evaluate(
            "() => document.getElementById('ce-run-note')?.textContent || ''"
        )
        print(f"[2b] run-note: {run_note!r}", flush=True)

        # 3. Điền đủ mailbox → toast "Đã thêm 1"
        page.fill(
            "#ce-mailbox-input",
            "ngadangmeow_mb500@hotmail.com|mp1|M.C111_BAY.0.U.-x|9e5f94bc-e8a4-4e73-b8be-63364c29d753",
        )
        page.click("#ce-btn-run")
        time.sleep(1.5)
        toast_text2 = page.evaluate(
            "() => [...document.querySelectorAll('.gpt-toast-msg')].map(e => e.textContent).join(' | ')"
        )
        print(f"[3] toast sau Run (đủ khung): {toast_text2!r}", flush=True)
        jobs_text = page.inner_text("#ce-job-list")
        print(f"[3b] jobs: {'ngadangmeow+500' in jobs_text}", flush=True)

        if console_errors:
            print("CONSOLE ERRORS:", flush=True)
            for e in console_errors[:15]:
                print(f"  {e[:250]}", flush=True)
        else:
            print("no console errors", flush=True)

        # Stop All dọn job giả
        try:
            page.click("#ce-btn-stop-all")
        except Exception:  # noqa: BLE001
            pass
        browser.close()

    ok = alert_visible and "Đã thêm 0" in (toast_text or "") and "Đã thêm 1" in (toast_text2 or "")
    print("RUN NOTIFICATION CHECK " + ("PASS" if ok else "FAIL"), flush=True)
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()