"""Smoke test: _solve_turnstile_inpage qua flow thật.

Đi đúng flow site: mở trang → btn-signin → login dialog → "Đăng ký ngay" →
register form (Turnstile chỉ render ở đây) → inject widget riêng → chờ
auto-solve/click → kiểm tra hidden input cf-turnstile-response có token.
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "web"))

from web.eventista import (  # noqa: E402
    _SITE_URL,
    _click_by_text,
    _launch_browser,
    _sitekey,
    _solve_turnstile_inpage,
)


async def main() -> int:
    print("── launch Camoufox ──")
    page, _handle, close = await _launch_browser(
        "camoufox", headless=False, proxy=None
    )
    try:
        await page.goto(_SITE_URL, wait_until="domcontentloaded", timeout=60000)
        print("[PASS] mở trang OK")

        await page.wait_for_selector('[data-id="btn-signin"]', state="attached", timeout=30000)
        clicked = await page.evaluate(
            """() => {
                const els = [...document.querySelectorAll('[data-id="btn-signin"]')];
                const el = els.find(e => e.offsetParent !== null);
                if (!el) return false;
                el.click();
                return true;
            }"""
        )
        if not clicked:
            print("[FAIL] btn-signin không bấm được")
            return 1
        await page.wait_for_selector("#login-form", state="visible", timeout=10000)
        print("[PASS] mở dialog Đăng nhập")

        if not await _click_by_text(page, "Đăng ký ngay"):
            print("[FAIL] không bấm được 'Đăng ký ngay'")
            return 1
        await page.locator("#register-form").wait_for(state="visible", timeout=15000)
        print("[PASS] mở form đăng ký (Turnstile render ở đây)")

        await asyncio.sleep(3.0)
        sitekey = await _sitekey(page)
        print(f"sitekey: {sitekey}")
        if not sitekey:
            print("[FAIL] không trích được sitekey")
            return 1
        print("[PASS] sitekey OK")

        print("── solve in-page ──")
        await _solve_turnstile_inpage(
            page, sitekey, log=lambda m: print(f"   {m}")
        )
        token = await page.evaluate(
            """() => {
                const el = document.querySelector('input[name="cf-turnstile-response"]');
                return el ? el.value : '';
            }"""
        )
        if not token or len(token) < 50:
            print(f"[FAIL] hidden input không có token: {str(token)[:40]!r}")
            return 1
        print(f"[PASS] token OK ({len(token)} ký tự)")
        print("[RESULT] all checks ok")
        return 0
    finally:
        try:
            await close()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))