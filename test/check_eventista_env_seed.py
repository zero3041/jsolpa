"""Verify: env YESCAPTCHA_CLIENT_KEY seed đúng vào EventistaManager.apply_settings.

Case 1: không có key trong settings + env có value → key = env.
Case 2: settings có eventista.yescaptcha_key → thắng env.
Case 3: không có gì → None.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ["YESCAPTCHA_CLIENT_KEY"] = "env-key-123"

from web.eventista import EventistaManager, _env, _YESCAPTCHA_ENV_KEY

ok = True

if _env("YESCAPTCHA_CLIENT_KEY", "") != "env-key-123":
    print("[FAIL] _env không đọc được YESCAPTCHA_CLIENT_KEY")
    ok = False
else:
    print("[PASS] _env đọc YESCAPTCHA_CLIENT_KEY")

if _YESCAPTCHA_ENV_KEY != "env-key-123":
    print(f"[FAIL] _YESCAPTCHA_ENV_KEY = {_YESCAPTCHA_ENV_KEY!r}")
    ok = False
else:
    print("[PASS] _YESCAPTCHA_ENV_KEY = env-key-123")

em = EventistaManager(max_concurrent=1)
em.apply_settings({})
if em.yescaptcha_key != "env-key-123":
    print(f"[FAIL] apply_settings dict rong khong seed env: {em.yescaptcha_key!r}")
    ok = False
else:
    print("[PASS] seed env khi DB trống")

em2 = EventistaManager(max_concurrent=1)
em2.apply_settings({"eventista.yescaptcha_key": "db-key-456"})
if em2.yescaptcha_key != "db-key-456":
    print(f"[FAIL] settings không thắng env: {em2.yescaptcha_key!r}")
    ok = False
else:
    print("[PASS] settings DB thắng env")

print("[RESULT]", "OK" if ok else "FAIL")
sys.exit(0 if ok else 1)