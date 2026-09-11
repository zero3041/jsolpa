"""Lấy token web.auth_token từ đúng DB path runtime/data.db."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db import get_engine, get_settings_repo  # noqa: E402

engine = get_engine(str(ROOT / "runtime" / "data.db"))
repo = get_settings_repo(engine)
val = repo.get("web.auth_token")
print(f"web.auth_token = {val.strip() if isinstance(val, str) and val.strip() else '(empty)'}")