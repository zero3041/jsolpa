"""Smoke: chạy flow Đổi Email thật (1 job) — gọi trực tiếp pipeline.

Input đọc từ env — KHÔNG hardcode credentials vào file:

    $env:CE_ACCOUNT = "riadaoon+4@outlook.com|Vote@sol"
    $env:CE_MAILBOX = "emailmoi@hotmail.com|pwd1|M.C548...|9e5f94bc-..."

Env tuỳ chọn:
    CE_ENGINE        (default camoufox)  camoufox|playwright|chrome|cloakbrowser
    CE_HEADLESS      (default 0)         1 = ẩn browser
    CE_CAPTCHA_MODE  (default click)     auto|click|yescaptcha|ezsolver|camoufox|inpage|none
    CE_CANDIDATE     (default "Xoay Vòng")
    CE_CATEGORY      (default "THE GROUP PERFORMANCE ICON")
    CE_POLL_TIMEOUT  (default 600)
    CE_PROXY         (rỗng = direct)
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")

from mail_providers import OutlookCombo  # noqa: E402
from web.change_email import (  # noqa: E402
    _POLL_INTERVAL_SECONDS,
    _SINCE_MARGIN_SECONDS,
    _do_change_email_request,
    _find_change_email_link,
    _open_change_link,
    _parse_account,
    _parse_mailbox,
)
from web.eventista import _launch_browser, _resolve_browser_engine  # noqa: E402


def _env(name: str, default: str) -> str:
    return os.environ.get(name) or default


def _log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def _read_inputs() -> tuple[str, str]:
    account = (os.environ.get("CE_ACCOUNT") or "").strip()
    mailbox = (os.environ.get("CE_MAILBOX") or "").strip()
    if not account or not mailbox:
        raise SystemExit(
            "Thiếu input — set env CE_ACCOUNT (email|password) + CE_MAILBOX (email|pwd|M.C..|uuid)"
        )
    return account, mailbox


async def _run(account: str, mailbox: str) -> int:
    old_email, old_pw = _parse_account(account)
    combo = _parse_mailbox(mailbox)
    new_email = combo.email
    engine = _env("CE_ENGINE", "camoufox")
    headless = _env("CE_HEADLESS", "0") == "1"
    captcha_mode = _env("CE_CAPTCHA_MODE", "click")
    candidate = _env("CE_CANDIDATE", "Xoay Vòng")
    category = _env("CE_CATEGORY", "THE GROUP PERFORMANCE ICON")
    poll_timeout = float(_env("CE_POLL_TIMEOUT", "600"))
    proxy = os.environ.get("CE_PROXY") or None

    _log(f"job: {old_email} → {new_email}")
    _log(
        f"engine={engine} headless={headless} captcha={captcha_mode} "
        f"proxy={proxy or 'direct'}"
    )

    engine = _resolve_browser_engine(engine, log=_log)
    combo_outlook = OutlookCombo(
        email=new_email, password=combo.password, refresh_token=combo.refresh_token,
        client_id=combo.client_id,
    )
    since = (
        datetime.now(timezone.utc) - timedelta(seconds=_SINCE_MARGIN_SECONDS)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    page, _handle, close = await _launch_browser(
        engine,
        headless=headless,
        proxy=proxy,
        camoufox_captcha=(engine == "camoufox" and captcha_mode == "camoufox"),
    )
    try:
        await _do_change_email_request(
            page,
            old_email=old_email,
            old_password=old_pw,
            new_email=new_email,
            category=category,
            candidate=candidate,
            captcha_mode=captcha_mode,
            yescaptcha_key=os.environ.get("CE_YESCAPTCHA_KEY") or None,
            proxy=proxy,
            log=_log,
        )

        _log(f"● Đợi mail kích hoạt — poll Graph trực tiếp (không proxy) tối đa {int(poll_timeout)}s")
        link: str | None = None
        deadline = time.monotonic() + poll_timeout
        while time.monotonic() < deadline:
            link = await _find_change_email_link(
                combo_outlook, proxy=None, since=since, log=_log
            )
            if link:
                break
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
        if not link:
            _log("✗ không tìm thấy link xác nhận trong mail")
            return 1

        await _open_change_link(page, link, log=_log)
    finally:
        try:
            await close()
        except Exception as exc:  # noqa: BLE001
            _log(f"close browser: {exc}")

    _log(f"✓ SUCCESS: {old_email}|{new_email}|{old_pw}")
    return 0


def main() -> None:
    account, mailbox = _read_inputs()
    raise SystemExit(asyncio.run(_run(account, mailbox)))


if __name__ == "__main__":
    main()