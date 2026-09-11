"""Smoke test: EzSolver service + solve thật qua web.eventista.

Kiểm tra:
1. `_ezsolver_ensure_service()` — service HTTP 8191 được spawn tự động.
2. `_ezsolver_solve(sitekey, siteurl)` — trả token thật từ Chrome.
3. Sitekey detection trên HTML thật của trang (mô phỏng `_sitekey` regex).
"""
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web"))

import httpx

from web.eventista import (
    _ezsolver_ensure_service,
    _ezsolver_solve,
)


async def main() -> int:
    print("── 1. ensure service ──")
    try:
        _ezsolver_ensure_service()
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] ensure_service: {exc}")
        return 1
    print("[PASS] service spawned (hoặc đã chạy)")

    async with httpx.AsyncClient(timeout=5.0) as client:
        health = await client.get("http://127.0.0.1:8191/health")
        print(f"[INFO] /health -> {health.json()}")

    print("── 2. solve thật ──")
    try:
        token = await _ezsolver_solve(
            "0x4AAAAAACzQ71rtjbtFwyuA",
            "https://tinhhasayhi.1vote.vn/",
            log=lambda m: print(f"   {m}"),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] solve: {exc}")
        return 1
    if not token.startswith("1."):
        print(f"[FAIL] token lạ: {token[:40]!r}")
        return 1
    print(f"[PASS] token OK ({len(token)} ký tự, bắt đầu bằng 1.)")

    print("── 3. sitekey detection (HTML thật + JS chunks) ──")
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        resp = await client.get("https://tinhhasayhi.1vote.vn/")
        html = resp.text
        m = re.search(r"0x[A-Za-z0-9_]{15,}", html)
        if not m:
            srcs = re.findall(r'src="([^"]+\.js[^"]*)"', html)
            for src in srcs:
                if not src.startswith("http"):
                    src = "https://tinhhasayhi.1vote.vn" + src
                try:
                    r = await client.get(src)
                    m = re.search(r"0x[A-Za-z0-9_]{15,}", r.text)
                    if m:
                        break
                except Exception:  # noqa: BLE001
                    continue
        if not m:
            print("[FAIL] không tìm thấy sitekey trong HTML/JS chunks")
            return 1
        print(f"[PASS] sitekey phát hiện: {m.group(0)}")

    print("[RESULT] all checks ok")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
