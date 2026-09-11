"""Verify _proxy_to_camoufox_dict parse đúng các dạng proxy URL."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from web.eventista import _proxy_to_camoufox_dict  # noqa: E402

ok = True
cases = [
    # (input, expected)
    ("http://user1:pass1@1.2.3.4:8080",
     {"server": "http://1.2.3.4:8080", "username": "user1", "password": "pass1"}),
    ("http://1.2.3.4:8080",
     {"server": "http://1.2.3.4:8080", "username": None, "password": None}),
    ("socks5://user2:pass2@host.example:1080",
     {"server": "socks5://host.example:1080", "username": "user2", "password": "pass2"}),
    ("1.2.3.4:8080",
     {"server": "http://1.2.3.4:8080", "username": None, "password": None}),
    # materialize_proxy URL-encode credential (quote safe="") → phải unquote
    ("http://christopher1398:nzgwnde0ndi4mzg%3D@103.216.74.218:4604",
     {"server": "http://103.216.74.218:4604",
      "username": "christopher1398", "password": "nzgwnde0ndi4mzg="}),
]
for raw, expected in cases:
    got = _proxy_to_camoufox_dict(raw)
    if got != expected:
        print(f"[FAIL] {raw!r} → {got!r}, expected {expected!r}")
        ok = False
    else:
        print(f"[PASS] {raw!r}")

if _proxy_to_camoufox_dict(None) is None:
    print("[PASS] None → None")
else:
    print("[FAIL] None → không phải None")
    ok = False

print("[RESULT]", "OK" if ok else "FAIL")
sys.exit(0 if ok else 1)