"""Verify môi trường Camoufox sau setup: binary, GeoIP mmdb, launch thật.

Chạy:
    .venv\\Scripts\\python test\\setup_verify_camoufox.py
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")


def _check_package_files() -> None:
    import camoufox

    from camoufox.pkgman import LOCAL_DATA

    mmdb = Path(LOCAL_DATA) / "GeoLite2-City.mmdb"
    print(f"[1] camoufox package: {camoufox.__file__}", flush=True)
    print(f"[2] GeoLite2-City.mmdb: {mmdb} ({mmdb.stat().st_size / 1_048_576:.1f} MB)" if mmdb.exists()
          else f"[2] GeoLite2-City.mmdb: THIẾU — {mmdb}", flush=True)
    if not mmdb.exists():
        raise SystemExit(2)

    from camoufox.pkgman import INSTALL_DIR

    bins = [p for p in INSTALL_DIR.rglob("*.exe")] if sys.platform == "win32" else \
        [p for p in INSTALL_DIR.rglob("camoufox")]
    print(f"[3] browser binary: {len(bins)} exe — {bins[0] if bins else 'KHÔNG CÓ'} "
          f"(install dir: {INSTALL_DIR})", flush=True)
    if not bins:
        raise SystemExit(3)


async def _probe_launch() -> None:
    print("[4] launch AsyncCamoufox (headless, geoip=True, direct)...", flush=True)
    from camoufox.async_api import AsyncCamoufox

    started = time.monotonic()
    cf = AsyncCamoufox(headless=True, geoip=True)
    try:
        browser = await asyncio.wait_for(cf.__aenter__(), timeout=180)
        page = await browser.new_page()
        await asyncio.wait_for(
            page.goto("https://example.com", wait_until="domcontentloaded", timeout=60000),
            timeout=90,
        )
        title = await page.title()
        print(f"[5] mở trang OK trong {time.monotonic() - started:.1f}s — title={title!r}", flush=True)
    finally:
        await cf.__aexit__(None, None, None)
    print(f"[6] total launch+page: {time.monotonic() - started:.1f}s", flush=True)


def main() -> None:
    _check_package_files()
    asyncio.run(_probe_launch())
    print("CAMOUFOX ENV OK", flush=True)


if __name__ == "__main__":
    main()