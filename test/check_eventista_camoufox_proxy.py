"""Verify: dict proxy từ _proxy_to_camoufox_dict chạy qua camoufox.Proxy thật.

Mô phỏng chính xác path launch Camoufox: Proxy(**dict) → as_string() → public_ip.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from web.eventista import _proxy_to_camoufox_dict  # noqa: E402

ok = True

raw_url = "http://christopher1398:nzgwnde0ndi4mzg=@103.216.74.218:4604"
d = _proxy_to_camoufox_dict(raw_url)
print(f"dict: {d!r}")

from camoufox.ip import Proxy  # noqa: E402

p = Proxy(**d)
as_str = p.as_string()
print(f"as_string: {as_str!r}")
if as_str != raw_url:
    print(f"[FAIL] as_string != raw_url: {as_str!r}")
    ok = False
else:
    print("[PASS] Proxy(**dict).as_string() roundtrip đúng")

# Playwright proxy shape — server/username/password tách riêng
if d["server"] != "http://103.216.74.218:4604":
    print(f"[FAIL] server: {d['server']!r}")
    ok = False
else:
    print("[PASS] server tách đúng host:port")
if d["username"] != "christopher1398" or d["password"] != "nzgwnde0ndi4mzg=":
    print(f"[FAIL] creds: {d['username']!r} / {d['password']!r}")
    ok = False
else:
    print("[PASS] username/password tách đúng")

print("[RESULT]", "OK" if ok else "FAIL")
sys.exit(0 if ok else 1)