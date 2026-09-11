"""UI test: tab Đổi Email — bấm Run, job phải hiện trong Jobs panel.

Dùng Playwright (channel chrome thật) load web UI, điền 2 khung, bấm Run,
verify jobs list cập nhật + bắt console error. Server phải đang chạy.
"""
from __future__ import annotations

import sys
import time

sys.path.insert(0, ".")

BASE = "http://127.0.0.1:8083"


def main() -> None:
    from playwright.sync_api import sync_playwright

    console_errors: list[str] = []
    failed_requests: list[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            channel="chrome",
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = browser.new_page(viewport={"width": 1600, "height": 900})
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: console_errors.append(f"PAGEERROR: {exc}"))

        def _on_response(resp) -> None:
            if resp.status >= 400 and "/static/" not in resp.url:
                failed_requests.append(f"{resp.request.method} {resp.url} → {resp.status}")

        page.on("response", _on_response)

        page.goto(BASE, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector('.tab-btn[data-tab="change-email"]', timeout=15000)
        page.click('.tab-btn[data-tab="change-email"]')
        time.sleep(1)

        # Verify tab active
        active = page.evaluate("() => document.querySelector('#tab-change-email').classList.contains('active')")
        print(f"tab active: {active}", flush=True)
        if not active:
            browser.close()
            raise SystemExit(1)

        # Điền 2 khung
        page.fill(
            "#ce-account-input",
            "ui_test_acc1@outlook.com|Vote@sol\nui_test_acc2@outlook.com|Vote@sol",
        )
        page.fill(
            "#ce-mailbox-input",
            "ui_test_mb1@hotmail.com|mp1|M.C111_BAY.0.U.-x|9e5f94bc-e8a4-4e73-b8be-63364c29d753\n"
            "ui_test_mb2@hotmail.com|mp2|M.C222_BAY.0.U.-y|9e5f94bc-e8a4-4e73-b8be-63364c29d753",
        )

        page.click("#ce-btn-run")
        print("clicked Run — chờ jobs xuất hiện...", flush=True)

        # Chờ jobs list có row
        ok = False
        for _ in range(20):
            time.sleep(0.5)
            text = page.inner_text("#ce-job-list")
            if "ui_test_acc1@outlook.com" in text and "ui_test_acc2@outlook.com" in text:
                ok = True
                break
        print(f"jobs rendered: {ok}", flush=True)
        print("job-list text:", flush=True)
        print(page.inner_text("#ce-job-list")[:500], flush=True)
        print("summary:", page.inner_text("#ce-job-summary"), flush=True)

        # Chờ job chuyển running (giống eventista: "N total · N running")
        running_seen = False
        for _ in range(30):
            time.sleep(0.5)
            if "running" in page.inner_text("#ce-job-summary"):
                running_seen = True
                break
        print(f"running seen: {running_seen} — summary: {page.inner_text('#ce-job-summary')}", flush=True)

        # Nút cancel per-job: huỷ job queued (job 2)
        cancel_ok = False
        cancel_resp: list[str] = []

        def _capture_cancel(resp) -> None:
            if "/cancel" in resp.url:
                try:
                    cancel_resp.append(f"{resp.status} {resp.text()}")
                except Exception as exc:  # noqa: BLE001
                    cancel_resp.append(f"{resp.status} (body err: {exc})")

        page.on("response", _capture_cancel)
        rows = page.query_selector_all("#ce-job-list .job")
        for row in rows:
            if "ui_test_acc2@outlook.com" in row.inner_text():
                btn = row.query_selector('[data-action="cancel"]')
                if btn:
                    btn.click()
                    cancel_ok = True
                break
        print(f"cancel button clicked (queued job): {cancel_ok}", flush=True)
        if cancel_ok:
            time.sleep(3)
            print(f"cancel response: {cancel_resp}", flush=True)
            text = page.inner_text("#ce-job-list")
            print(f"cancelled rendered: {'cancelled' in text}", flush=True)
            print("job-list after cancel:", flush=True)
            print(text[:600], flush=True)

        # Stop All để không launch browser thật
        try:
            page.click("#ce-btn-stop-all")
            time.sleep(1)
            print("stop-all clicked", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"stop-all fail: {exc}", flush=True)

        if console_errors:
            print("CONSOLE ERRORS:", flush=True)
            for e in console_errors[:20]:
                print(f"  {e[:300]}", flush=True)
        else:
            print("no console errors", flush=True)

        if failed_requests:
            print("FAILED REQUESTS:", flush=True)
            for r in failed_requests[:20]:
                print(f"  {r}", flush=True)

        browser.close()

    if not ok:
        raise SystemExit(1)
    print("UI TEST PASS", flush=True)


if __name__ == "__main__":
    main()