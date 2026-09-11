"""Debug: click chuột thật vào tâm YouTube iframe → video có play không.
Đo qua: src iframe đổi autoplay, body text đếm ngược "30" → 29...
"""
from __future__ import annotations

import asyncio
import json
import sys

sys.path.insert(0, ".")

from web.eventista import _launch_browser, _resolve_browser_engine  # noqa: E402
from web.vote import (  # noqa: E402
    _click_candidate_vote,
    _click_vote_package,
    _do_login,
    _open_login_dialog,
    _open_video,
)

EMAIL = "taolaban007@gmail.com"
PASSWORD = "Bss123@#"
PROXY = "http://christopher1398:nzgwnde0ndi4mzg=@103.216.74.218:4604"


async def state(page):
    return await page.evaluate(
        """() => ({
            src: [...document.querySelectorAll('iframe')].map(f => (f.src || '').slice(0, 90)),
            body_tail: (document.body ? document.body.innerText : '').slice(-200),
        })"""
    )


async def main() -> None:
    engine = _resolve_browser_engine("camoufox", log=print)
    page, handle, close = await _launch_browser(engine, headless=True, proxy=PROXY)
    log = lambda m: print(m)
    try:
        await page.goto("https://tinhhasayhi.1vote.vn", wait_until="domcontentloaded", timeout=60000)
        await _open_login_dialog(page, log)
        await _do_login(page, email=EMAIL, password=PASSWORD, log=log)
        await _click_candidate_vote(page, candidate="Anh Trai JSOL", log=log)
        await _click_vote_package(page, log)
        await _open_video(page, log)

        await asyncio.sleep(2)
        print("trước click iframe:", json.dumps(await state(page), ensure_ascii=False))

        iframe = page.locator("iframe[src*='youtube.com/embed']").first
        box = await iframe.bounding_box()
        print("iframe bbox:", box)
        if box:
            await page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)

        for i in range(3):
            await asyncio.sleep(5)
            s = await state(page)
            print(f"t+{(i + 1) * 5}s sau click iframe:", json.dumps(s, ensure_ascii=False))
            if "29" in s["body_tail"] or "28" in s["body_tail"] or "27" in s["body_tail"] or "26" in s["body_tail"]:
                print(">>> COUNTDOWN GIẢM — video đang play")
                break
    finally:
        await close()


if __name__ == "__main__":
    asyncio.run(main())
