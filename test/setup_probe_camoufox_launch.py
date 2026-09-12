"""Diagnose Camoufox launch (async): headless vs headed, in lỗi thật.

Chạy: .venv\\Scripts\\python test\\setup_probe_camoufox_launch.py
"""
from __future__ import annotations

import asyncio
import importlib.metadata as md
import sys
import time

sys.path.insert(0, ".")


def _version() -> None:
    print(f"camoufox: {md.version('camoufox')}", flush=True)
    print(f"playwright: {md.version('playwright')}", flush=True)
    print(f"geoip2: {md.version('geoip2')}", flush=True)


async def _try_launch(name: str, **kwargs) -> None:
    from camoufox.async_api import AsyncCamoufox

    started = time.monotonic()
    print(f"[{name}] launch ...", flush=True)
    cf = AsyncCamoufox(**kwargs)
    try:
        browser = await asyncio.wait_for(cf.__aenter__(), timeout=120)
        page = await browser.new_page()
        await page.goto("about:blank")
        print(f"[{name}] OK — launch {time.monotonic() - started:.1f}s", flush=True)
        await page.close()
    except Exception as exc:  # noqa: BLE001
        print(f"[{name}] FAIL sau {time.monotonic() - started:.1f}s: "
              f"{type(exc).__name__}: {str(exc)[:300]}", flush=True)
    finally:
        try:
            await cf.__aexit__(None, None, None)
        except Exception:  # noqa: BLE001
            pass


async def main() -> None:
    _version()
    await _try_launch("headless+geoip", headless=True, geoip=True)
    await _try_launch("headed+geoip", headless=False, geoip=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    asyncio.run(main())