"""Đọc Hòm Thư — check Outlook combo còn sống không + đọc N thư mới nhất.

Flow mỗi combo (format `email|password|refresh_token|client_id`, Graph API / OAuth2):
  1. Refresh access token qua login.microsoftonline.com.
  2. Token OK  → ALIVE, fetch `max_messages` thư mới nhất từ Graph API.
  3. Token fail → DEAD, kèm lý do (invalid_grant / expired / disabled / ...).

KHÔNG persist refresh token ở đây (check-only tool) — tránh vô tình rotate
token khi user chỉ muốn kiểm tra. Dùng chung hằng số + timeout với
`OutlookMailProvider` (mail_providers.py) để không lệch behavior.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from mail_providers import (
    OutlookCombo,
    OutlookComboError,
    _DEFAULT_SCOPE,
    _GRAPH_BASE,
    _OUTLOOK_AUTH_FATAL_KEYS,
    _OUTLOOK_HTTP_TIMEOUT,
    _TOKEN_URL,
)

_log = logging.getLogger(__name__)

# Giới hạn số thư tối đa lấy được trên 1 account (Graph `$top`).
_MAX_MESSAGES_CAP = 50
# Concurrency mặc định khi check nhiều combo.
_DEFAULT_CONCURRENCY = 10


class MailReaderParseError(Exception):
    """Parse combo fail (format sai)."""


class MailReaderError(Exception):
    """Check mail fail tổng thể (network/provider)."""


def _parse_lines(text: str) -> list[str]:
    """Split textarea thành list dòng không rỗng / không comment."""
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def parse_combos(text: str) -> list[OutlookCombo]:
    """Parse textarea thành list combo Outlook hợp lệ.

    Raises:
        MailReaderParseError: combo đầu tiên sai format (fail-fast — báo rõ dòng).
    """
    lines = _parse_lines(text)
    combos: list[OutlookCombo] = []
    for line in lines:
        try:
            combos.append(OutlookCombo.parse(line))
        except OutlookComboError as exc:
            raise MailReaderParseError(f"{exc} — dòng: {line[:120]}") from exc
    return combos


async def _refresh_access(client: httpx.AsyncClient, combo: OutlookCombo) -> str:
    """Refresh access token. Raise OutlookComboError (dead) / OutlookProviderUnavailable (transient).

    Scope: thử nhiều scope theo thứ tự. Nhiều combo được cấp qua reader site
    (thsh.vjpprono1.dev/reader) chỉ hoạt động với scope delegated cụ thể
    (`offline_access Mail.Read`) — scope `.default` trả AADSTS90023 "No
    applicable permissions" vì client_id không có static permission cho user.
    """
    from mail_providers import OutlookProviderUnavailable

    scopes = (
        "offline_access Mail.Read",
        _DEFAULT_SCOPE,
    )

    last_fatal: str | None = None
    for scope in scopes:
        response = await client.post(
            _TOKEN_URL,
            data={
                "client_id": combo.client_id,
                "scope": scope,
                "refresh_token": combo.refresh_token,
                "grant_type": "refresh_token",
            },
        )
        if response.status_code == 200:
            data = response.json()
            access = data.get("access_token")
            if not access:
                raise OutlookComboError(f"refresh response missing access_token: {data}")
            return access

        body = response.text[:500]
        fatal = any(key in body for key in _OUTLOOK_AUTH_FATAL_KEYS)
        if fatal or 400 <= response.status_code < 500:
            # Lỗi 4xx/thuộc fatal — thử scope kế; lỗi chết vĩnh viễn được xét
            # sau cùng vì scope khác có thể vẫn refresh được token.
            last_fatal = f"scope={scope!r} HTTP {response.status_code}: {body}"
            continue
        raise OutlookProviderUnavailable(
            f"refresh transient HTTP {response.status_code}: {body[:200]}"
        )

    raise OutlookComboError(
        f"refresh failed với mọi scope. Last: {last_fatal}"
    )


async def _list_messages(
    client: httpx.AsyncClient,
    access_token: str,
    max_messages: int,
) -> list[dict[str, Any]]:
    """Lấy `max_messages` thư mới nhất (subject, from, receivedDateTime, bodyPreview)."""
    top = max(1, min(max_messages, _MAX_MESSAGES_CAP))
    resp = await client.get(
        f"{_GRAPH_BASE}/me/messages",
        params={
            "$top": top,
            "$orderby": "receivedDateTime desc",
            "$select": "subject,from,receivedDateTime,bodyPreview,isRead",
        },
        headers={"Authorization": f"Bearer {access_token}"},
    )
    resp.raise_for_status()
    return resp.json().get("value", [])


def _message_summary(msg: dict[str, Any]) -> dict[str, Any]:
    """Trích field an toàn từ 1 message Graph → dict nhỏ gọn cho UI."""
    from_obj = msg.get("from") or {}
    sender = (from_obj.get("emailAddress") or {}).get("address", "")
    body_preview = (msg.get("bodyPreview") or "").strip()
    return {
        "subject": msg.get("subject") or "",
        "from": sender,
        "received": msg.get("receivedDateTime") or "",
        "is_read": bool(msg.get("isRead")),
        "preview": body_preview[:500],
    }


async def check_one(
    combo: OutlookCombo,
    *,
    max_messages: int,
    proxy: str | None = None,
) -> dict[str, Any]:
    """Check 1 combo: ALIVE (đọc được thư) hoặc DEAD kèm lý do.

    Returns:
        {
          "email": ..., "status": "alive"|"dead"|"parse_error"|"network_error",
          "message_count": int, "messages": [...], "error": str | None,
        }
    """
    result: dict[str, Any] = {
        "email": combo.email,
        "status": "dead",
        "message_count": 0,
        "messages": [],
        "error": None,
    }

    kwargs: dict[str, Any] = {"timeout": _OUTLOOK_HTTP_TIMEOUT}
    if proxy:
        kwargs["proxy"] = proxy

    try:
        async with httpx.AsyncClient(**kwargs) as client:
            access = await _refresh_access(client, combo)
            messages = await _list_messages(client, access, max_messages)
    except OutlookComboError as exc:
        # Combo chết vĩnh viễn: token hết hạn / revoke / account disabled...
        result["error"] = str(exc)[:500]
        return result
    except (httpx.HTTPError, asyncio.TimeoutError) as exc:
        # Network fail — không kết luận combo chết, báo lỗi mạng riêng.
        result["status"] = "network_error"
        result["error"] = f"{type(exc).__name__}: {exc!r}"[:500]
        return result
    except Exception as exc:  # noqa: BLE001 — check-only tool, không crash cả batch
        result["status"] = "network_error"
        result["error"] = f"{type(exc).__name__}: {exc!r}"[:500]
        return result

    result["status"] = "alive"
    result["message_count"] = len(messages)
    result["messages"] = [_message_summary(m) for m in messages]
    return result


async def check_many(
    text: str,
    *,
    max_messages: int = 10,
    concurrency: int = _DEFAULT_CONCURRENCY,
    proxy: str | None = None,
) -> dict[str, Any]:
    """Check nhiều combo song song (semaphore giới hạn concurrency).

    Returns:
        {
          "total": int, "alive": int, "dead": int, "network_error": int,
          "parse_error": str | None, "results": [check_one result...],
        }
    """
    lines = _parse_lines(text)
    if not lines:
        return {
            "total": 0, "alive": 0, "dead": 0, "network_error": 0,
            "parse_error": "Không có combo nào để check", "results": [],
        }

    # Parse fail-fast: combo sai format → trả parse_error, không check phần còn lại.
    try:
        combos = parse_combos(text)
    except MailReaderParseError as exc:
        return {
            "total": len(lines), "alive": 0, "dead": 0, "network_error": 0,
            "parse_error": str(exc), "results": [],
        }

    sem = asyncio.Semaphore(max(1, concurrency))

    async def _limited(combo: OutlookCombo) -> dict[str, Any]:
        async with sem:
            return await check_one(combo, max_messages=max_messages, proxy=proxy)

    results = await asyncio.gather(*[_limited(c) for c in combos])

    alive = sum(1 for r in results if r["status"] == "alive")
    dead = sum(1 for r in results if r["status"] == "dead")
    network = sum(1 for r in results if r["status"] == "network_error")

    return {
        "total": len(results),
        "alive": alive,
        "dead": dead,
        "network_error": network,
        "parse_error": None,
        "results": results,
    }