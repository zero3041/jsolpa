"""Smoke test: camoufox_captcha.solve_captcha trên flow đăng ký thật.

Launch AsyncCamoufox với config bắt buộc (forceScopeAccess + disable_coop),
đi flow site → #register-form → solve_captcha(container #cf-turnstile,
challenge_type="turnstile") → kiểm tra hidden input có token.
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
    _proxy_to_camoufox_dict,
    _sitekey,
)

PROXY = "http://christopher1398:nzgwnde0ndi4mzg=@103.216.74.218:4604"


async def main() -> int:
    proxy_raw = PROXY
    print(f"proxy: {proxy_raw}")

    print("── launch AsyncCamoufox (forceScopeAccess + disable_coop) ──")
    from camoufox.async_api import AsyncCamoufox

    proxy_kwargs: dict = {}
    if proxy_raw:
        proxy_kwargs["proxy"] = _proxy_to_camoufox_dict(proxy_raw)
    cf = AsyncCamoufox(
        headless=False,
        geoip=bool(proxy_raw),
        config={"forceScopeAccess": True},
        disable_coop=True,
        **proxy_kwargs,
    )
    browser = await cf.__aenter__()
    try:
        page = await browser.new_page()
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

        container = page.locator("#cf-turnstile").first
        state = await container.evaluate(
            """el => ({
                hasShadow: !!el.shadowRoot,
                html: el.innerHTML.slice(0, 200),
                childCount: el.children.length,
                iframes: el.querySelectorAll('iframe').length,
            })"""
        )
        print(f"[DEBUG] #cf-turnstile: {state}")
        await asyncio.sleep(5.0)
        state2 = await container.evaluate(
            """el => ({
                hasShadow: !!el.shadowRoot,
                childCount: el.children.length,
                iframes: el.querySelectorAll('iframe').length,
                docIframes: document.querySelectorAll('iframe[src*="challenges.cloudflare.com"]').length,
            })"""
        )
        print(f"[DEBUG] #cf-turnstile sau 5s: {state2}")
        handle = await container.element_handle()

        print("── solve_captcha (cloudflare/turnstile) ──")
        from camoufox_captcha import solve_captcha

        success = await solve_captcha(
            handle,
            captcha_type="cloudflare",
            challenge_type="turnstile",
            solve_attempts=2,
            wait_checkbox_attempts=8,
            wait_checkbox_delay=3,
        )
        print(f"[INFO] solve_captcha → {success}")

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
            await cf.__aexit__(None, None, None)
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))