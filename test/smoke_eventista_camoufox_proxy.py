"""Smoke: launch Camoufox thật qua proxy từ pool config + goto site Eventista.

Dùng proxy pool từ Settings DB (giống hệt path job thật). Bỏ qua nếu pool rỗng.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("GSH_DB_PATH", str(ROOT / "runtime" / "data.db"))


async def main() -> bool:
    from db import get_engine, get_settings_repo
    from web.manager import _resolve_job_proxy
    from web.eventista import _launch_browser, _proxy_to_camoufox_dict

    engine = get_engine()
    settings = get_settings_repo(engine).list()
    stored = settings.get("proxy.pool") or []
    print(f"stored proxies: {len(stored)}")
    if not stored:
        print("settings chưa có proxy — skip smoke (không phải lỗi)")
        return True
    from web.proxy_pool import get_proxy_pool, normalize_proxies

    get_proxy_pool().configure(normalize_proxies(stored))
    proxy, line = await _resolve_job_proxy(log=lambda m: print("  proxy:", m))
    print(f"resolved proxy: {proxy[:50] if proxy else None}")
    if not proxy:
        print("pool rỗng/không live — skip smoke (không phải lỗi)")
        return True

    print(f"dict: {_proxy_to_camoufox_dict(proxy)!r}")
    page, _handle, close = await _launch_browser(
        "camoufox", headless=True, proxy=proxy
    )
    try:
        await page.goto("https://tinhhasayhi.1vote.vn", wait_until="domcontentloaded", timeout=45000)
        title = await page.title()
        print(f"[PASS] goto OK — title: {title[:60]}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] goto fail: {type(exc).__name__}: {str(exc)[:300]}")
        return False
    finally:
        try:
            await close()
        except Exception as exc:  # noqa: BLE001
            print("close fail:", exc)


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(main()) else 1)