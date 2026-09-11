"""Debug: sau khi bấm Bình chọn trên candidate, dump mọi button trong popup/modal
để biết text thật của gói "1 vote".
"""
from __future__ import annotations

import asyncio
import json
import sys

sys.path.insert(0, ".")

from web.eventista import _launch_browser, _resolve_browser_engine  # noqa: E402
from web.vote import _open_login_dialog, _do_login, _click_candidate_vote  # noqa: E402

EMAIL = "taolaban007@gmail.com"
PASSWORD = "Bss123@#"
PROXY = "http://christopher1398:nzgwnde0ndi4mzg=@103.216.74.218:4604"


async def main() -> None:
    engine = _resolve_browser_engine("camoufox", log=print)
    page, handle, close = await _launch_browser(engine, headless=True, proxy=PROXY)
    log = lambda m: print(m)
    try:
        await page.goto("https://tinhhasayhi.1vote.vn", wait_until="domcontentloaded", timeout=60000)
        await _open_login_dialog(page, log)
        await _do_login(page, email=EMAIL, password=PASSWORD, log=log)
        await _click_candidate_vote(page, candidate="Anh Trai JSOL", log=log)

        for i in range(8):
            await asyncio.sleep(1.5)
            buttons = await page.evaluate(
                """() => [...document.querySelectorAll('button')].map(b => ({
                    t: b.innerText.trim().slice(0, 120),
                    a: b.getAttribute('aria-label') || '',
                    cls: b.className.toString().slice(0, 60),
                    vis: b.offsetParent !== null,
                    disabled: b.disabled,
                }))"""
            )
            visible = [b for b in buttons if b["vis"]]
            if visible:
                print(f"--- t={i * 1.5}s visible buttons={len(visible)} ---")
                for b in visible:
                    print(json.dumps(b, ensure_ascii=False))
                popup_h = await page.evaluate(
                    """() => [...document.querySelectorAll('h2,h3,h4,.modal,.popup,[class*=modal],[class*=popup]')]
                        .filter(e => e.offsetParent !== null)
                        .slice(0, 8)
                        .map(e => `${e.tagName}.${e.className.toString().slice(0,40)}: ${e.innerText.slice(0,100)}`)"""
                )
                if popup_h:
                    print("--- popup headers ---")
                    for h in popup_h:
                        print(h)
                break
        else:
            print("KHÔNG thấy button visible nào sau khi bấm Bình chọn")
    finally:
        await close()


if __name__ == "__main__":
    asyncio.run(main())
