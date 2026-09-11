"""Smoke test: EzSolver solve qua proxy thật (IP phải khớp IP Camoufox).

Gọi service HTTP 8191 với payload có proxy → token phải trả về.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web"))

import httpx

from web.eventista import _ezsolver_ensure_service

PROXY = "http://christopher1398:nzgwnde0ndi4mzg=@103.216.74.218:4604"


async def main() -> int:
    print("── ensure service ──")
    try:
        _ezsolver_ensure_service()
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] ensure_service: {exc}")
        return 1
    print("[PASS] service OK")

    print(f"── solve qua proxy {PROXY.split('@')[1]} ──")
    async with httpx.AsyncClient(timeout=150.0) as client:
        resp = await client.post(
            "http://127.0.0.1:8191/solve",
            json={
                "sitekey": "0x4AAAAAACzQ71rtjbtFwyuA",
                "siteurl": "https://tinhhasayhi.1vote.vn/",
                "timeout": 100,
                "proxy": PROXY,
            },
        )
    print(f"HTTP {resp.status_code}")
    if resp.status_code != 200:
        print(f"[FAIL] {resp.text[:400]}")
        return 1
    data = resp.json()
    token = data.get("token") or ""
    if not token.startswith("1."):
        print(f"[FAIL] token lạ: {token[:40]!r}")
        return 1
    print(f"[PASS] token OK ({len(token)} ký tự) sau {data.get('elapsed')}s")
    print("[RESULT] all checks ok")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
