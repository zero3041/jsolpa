"""Smoke test mail_reader.check_many với httpx MockTransport (không gọi mạng).

Chạy: python3 test/smoke_mail_reader.py
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from web import mail_reader  # noqa: E402


def _mock_refresh_ok(client):
    """Patch OutlookMailProvider httpx client dùng MockTransport trả token OK."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "login.microsoftonline.com":
            return httpx.Response(
                200,
                json={"access_token": "fake-access", "token_type": "Bearer", "expires_in": 3600},
            )
        if "graph.microsoft.com" in request.url.host:
            return httpx.Response(
                200,
                json={"value": [
                    {"subject": "ChatGPT code: 123456",
                     "from": {"emailAddress": {"address": "no-reply@openai.com"}},
                     "receivedDateTime": "2026-08-13T10:00:00Z",
                     "bodyPreview": "Your code is 123456",
                     "isRead": False},
                    {"subject": "Newsletter",
                     "from": {"emailAddress": {"address": "news@example.com"}},
                     "receivedDateTime": "2026-08-12T09:00:00Z",
                     "bodyPreview": "Hello",
                     "isRead": True},
                ]},
            )
        return httpx.Response(404)
    return handler


def _mock_refresh_dead(client):
    """Token lỗi vĩnh viễn: invalid_grant."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "login.microsoftonline.com":
            return httpx.Response(
                400,
                json={"error": "invalid_grant", "error_description": "AADSTS70008 token expired"},
            )
        return httpx.Response(404)
    return handler


def _mock_refresh_network(client):
    """Network fail (timeout)."""
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("connection timed out")
    return handler


def _run_with_mock(mock_fn, combos_text, max_messages=5):
    """Chạy check_one với httpx.AsyncClient bị mock — chèn vào module-level httpx.AsyncClient."""
    import web.mail_reader as mr

    original = httpx.AsyncClient

    class MockedAsyncClient(original):
        def __init__(self, **kwargs):
            # Bỏ timeout thật, dùng MockTransport
            super().__init__(transport=httpx.MockTransport(mock_fn(None)), **kwargs)

    httpx.AsyncClient = MockedAsyncClient
    try:
        return asyncio.run(mr.check_many(combos_text, max_messages=max_messages))
    finally:
        httpx.AsyncClient = original


def _check(name, ok, detail=""):
    print(f"[{'OK' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def main() -> int:
    ok = True

    combo_alive = "user@hotmail.com|pass|M.C524_BAY.0.U.-abc|9e5f94bc-0000-0000-0000-000000000000"
    combo_dead = "dead@hotmail.com|pass|M.C525_BAY.0.U.-def|8b4ba9dd-0000-0000-0000-000000000000"
    combo_net = "net@hotmail.com|pass|M.C526_BAY.0.U.-ghi|8b4ba9dd-0000-0000-0000-000000000000"

    # 1. Alive: token OK + 2 thư
    text = "\n".join([combo_alive])
    res = _run_with_mock(_mock_refresh_ok, text)
    ok &= _check("alive: status", res["results"][0]["status"] == "alive", str(res))
    ok &= _check("alive: message_count==2", res["results"][0]["message_count"] == 2)
    ok &= _check("alive: subject parsed", res["results"][0]["messages"][0]["subject"] == "ChatGPT code: 123456")
    ok &= _check("alive: summary counts", res["alive"] == 1 and res["dead"] == 0 and res["total"] == 1)

    # 2. Dead: invalid_grant
    res = _run_with_mock(_mock_refresh_dead, combo_dead)
    ok &= _check("dead: status", res["results"][0]["status"] == "dead", str(res))
    ok &= _check("dead: error contains invalid_grant", "invalid_grant" in (res["results"][0]["error"] or ""))

    # 3. Network error
    res = _run_with_mock(_mock_refresh_network, combo_net)
    ok &= _check("network: status", res["results"][0]["status"] == "network_error", str(res))

    # 4. Mixed batch
    text = "\n".join([combo_alive, combo_dead])
    res = _run_with_mock(_mock_refresh_ok if False else _mock_refresh_ok, text)  # placeholder
    # Chạy lại đúng: alive + dead chung batch — mock trả ok cho cả 2 (cùng handler)
    res = _run_with_mock(_mock_refresh_ok, text)
    ok &= _check("batch total", res["total"] == 2)
    ok &= _check("batch alive==2 (same mock)", res["alive"] == 2)

    # 5. Parse error: combo sai format
    res = asyncio.run(mail_reader.check_many("không-có-pipe-ký-tự@hotmail.com"))
    ok &= _check("parse_error trả về", res["parse_error"] is not None and res["results"] == [], str(res.get("parse_error")))

    # 6. Empty input
    res = asyncio.run(mail_reader.check_many("  \n# comment\n"))
    ok &= _check("empty input", res["total"] == 0 and res["parse_error"] is not None)

    # 7. max_messages cap
    ok &= _check("cap 50", mail_reader._MAX_MESSAGES_CAP == 50)

    print("ALL OK" if ok else "HAS FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())