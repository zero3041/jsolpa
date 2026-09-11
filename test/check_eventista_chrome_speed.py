"""Đo thời gian: Chrome thật (channel=chrome) + proxy — launch + goto + widget render.

Chỉ đo tốc độ, không đăng ký. Giúp xác định "lag" do proxy/Chrome hay do logic.
"""
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "web"))

from web.eventista import _SITE_URL, _click_by_text, _launch_browser  # noqa: E402

PROXY = "http://christopher1398:nzgwnde0ndi4mzg=@103.216.74.218:4604"


async def main() -> int:
    t0 = time.monotonic()
    page, _h, close = await _launch_browser("chrome", headless=False, proxy=PROXY)
    print(f"[time] launch chrome+proxy: {time.monotonic()-t0:.1f}s")

    t1 = time.monotonic()
    await page.goto(_SITE_URL, wait_until="domcontentloaded", timeout=60000)
    print(f"[time] goto: {time.monotonic()-t1:.1f}s")

    t2 = time.monotonic()
    await page.wait_for_selector('[data-id="btn-signin"]', state="attached", timeout=30000)
    await page.evaluate(
        """() => {
            const els = [...document.querySelectorAll('[data-id="btn-signin"]')];
            const el = els.find(e => e.offsetParent !== null);
            if (el) el.click();
        }"""
    )
    await page.wait_for_selector("#login-form", state="visible", timeout=10000)
    await _click_by_text(page, "Đăng ký ngay")
    await page.locator("#register-form").wait_for(state="visible", timeout=15000)
    print(f"[time] tới form đăng ký: {time.monotonic()-t2:.1f}s")

    t3 = time.monotonic()
    for i in range(10):
        await asyncio.sleep(1.0)
        info = await page.evaluate(
            """() => {
                const el = document.querySelector('#cf-turnstile');
                const ifr = document.querySelector('iframe[src*="challenges.cloudflare.com"]');
                const inp = document.querySelector('input[name="cf-turnstile-response"]');
                return JSON.stringify({
                    widget: !!el, iframe: !!ifr,
                    token: (inp && inp.value) ? inp.value.length : 0,
                });
            }"""
        )
        print(f"   t+{i+1}s: {info}")
        if '"token":' in info and '"token": 0' not in info.replace('"token": 0', 'X'):
            pass
    print(f"[time] chờ widget: {time.monotonic()-t3:.1f}s")

    await close()
    print(f"[time] total: {time.monotonic()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))