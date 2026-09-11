"""Debug: so sánh chính xác dict proxy cho case bare host:port."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from web.eventista import _proxy_to_camoufox_dict  # noqa: E402

got = _proxy_to_camoufox_dict("1.2.3.4:8080")
expected = {"server": "http://1.2.3.4:8080", "username": None, "password": None}
print(f"got      = {got!r}")
print(f"expected = {expected!r}")
print("equal:", got == expected)
for k in expected:
    print(f"  {k}: got={got.get(k)!r} ({type(got.get(k)).__name__}) expected={expected[k]!r} ({type(expected[k]).__name__})")