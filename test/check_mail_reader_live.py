"""Live diagnostic: check combo thật qua đúng code path mail_reader.check_one.

Chạy: .venv/bin/python test/check_mail_reader_live.py
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from mail_providers import (  # noqa: E402
    OutlookCombo,
    _DEFAULT_SCOPE,
    _OUTLOOK_HTTP_TIMEOUT,
    _TOKEN_URL,
)
from web.mail_reader import check_one  # noqa: E402

COMBO = (
    "SheylaNetz595027@outlook.com|hvjkx09030|"
    "M.C520_BAY.0.U.MsaArtifacts.-CvcBN9fqBszEjWhlWGuAou8sp7vVmOJYDcxp9JbOPRNlnTtsrYrL42E9FBgjOPOOcUr7xfKZB!THeYMDkRois93ZCHq2oX9h*px!WEHlqLZotm47kGbfMr6Q14m3UD5Zn2PIimkUN9nbHUFQjOqz8jJ4aouOJ7np7QFBfpARyfWa1mX2yPv5GBzfOtaCEm2BZXqbnchrPC5bPAvVenYsR!xgUEoZ0RqoQxKoIqr*LOmpkNd0nCBwIyfb!fSHe6G!MtB8ulIZaUOszjq2IT9nlMJSzUzzw9kpn2D13bvMyyLBXF5TMr80SAISKkWLn8Y9DE75w5l*vDhjuwXheYHVbOP3qG7kxQa!6og4kJ7k9Lb!56HgGfp2Lwo!3Qvu0nYi8L!sJNwSW1oXD2gLvht3OAg6FjD8EPHh0ZcaX7eP6KZt|"
    "9e5f94bc-e8a4-4e73-b8be-63364c29d753"
)


async def _raw_refresh(combo: OutlookCombo, *, token_url: str, scope: str) -> httpx.Response:
    async with httpx.AsyncClient(timeout=_OUTLOOK_HTTP_TIMEOUT) as client:
        return await client.post(
            token_url,
            data={
                "client_id": combo.client_id,
                "scope": scope,
                "refresh_token": combo.refresh_token,
                "grant_type": "refresh_token",
            },
        )


async def main() -> int:
    combo = OutlookCombo.parse(COMBO)
    print(f"email:     {combo.email}")
    print(f"client_id: {combo.client_id}")
    print(f"refresh_token prefix: {combo.refresh_token[:24]}...")
    print()

    # 1. Đúng code path của tool
    result = await check_one(combo, max_messages=5)
    print("== check_one (consumers + .default) ==")
    print(f"status: {result['status']}")
    print(f"error:  {result['error']}")
    print()

    # 2. Refresh thô qua consumers endpoint — in đầy đủ body
    resp = await _raw_refresh(combo, token_url=_TOKEN_URL, scope=_DEFAULT_SCOPE)
    print(f"== raw refresh consumers, scope={_DEFAULT_SCOPE!r} ==")
    print(f"HTTP {resp.status_code}")
    print(resp.text[:800])
    print()

    # 3. Thử scope offline_access Mail.Read (không .default)
    resp = await _raw_refresh(combo, token_url=_TOKEN_URL, scope="offline_access Mail.Read")
    print("== raw refresh consumers, scope=offline_access Mail.Read ==")
    print(f"HTTP {resp.status_code}")
    print(resp.text[:800])
    print()

    # 4. Thử token_url = common (tenant-agnostic) thay vì consumers
    resp = await _raw_refresh(
        combo,
        token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
        scope=_DEFAULT_SCOPE,
    )
    print("== raw refresh common + .default ==")
    print(f"HTTP {resp.status_code}")
    print(resp.text[:800])
    print()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
