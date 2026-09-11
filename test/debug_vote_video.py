"""Debug: sau khi bấm Phát video, dump trạng thái video dialog sau 3s/15s/35s
(iframe youtube, countdown text, nút Bình chọn ngay, trạng thái video element).
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


async def dump(page, label: str) -> None:
    print(f"\n========== {label} ==========")
    try:
        data = await page.evaluate(
            """() => {
                const body = document.body ? document.body.innerText : '';
                return {
                    body_tail: body.slice(-1500),
                    iframes: [...document.querySelectorAll('iframe')].map(f => ({
                        src: (f.src || '').slice(0, 80),
                        vis: f.offsetParent !== null,
                    })),
                    videos: [...document.querySelectorAll('video')].map(v => ({
                        paused: v.paused,
                        cur: v.currentTime,
                        dur: v.duration,
                        vis: v.offsetParent !== null,
                    })),
                    confirm_btns: [...document.querySelectorAll('button')].filter(
                        b => b.innerText.includes('Bình chọn ngay')
                    ).map(b => ({
                        t: b.innerText.trim().slice(0, 60),
                        vis: b.offsetParent !== null,
                        disabled: b.disabled,
                    })),
                    countdown: [...document.querySelectorAll('span,[class*=countdown],[class*=timer]')]
                        .filter(e => e.offsetParent !== null && /\\d/.test(e.innerText) && e.innerText.length < 30)
                        .slice(0, 8)
                        .map(e => e.innerText.trim()),
                };
            }"""
        )
        print(json.dumps(data, ensure_ascii=False, indent=1))
    except Exception as exc:  # noqa: BLE001
        print(f"dump fail: {exc}")


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

        await asyncio.sleep(3)
        await dump(page, "t+3s sau click Phát video")

        await asyncio.sleep(12)
        await dump(page, "t+15s")

        await asyncio.sleep(20)
        await dump(page, "t+35s")
    finally:
        await close()


if __name__ == "__main__":
    asyncio.run(main())
