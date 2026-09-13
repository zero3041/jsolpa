"""Đếm vote success hôm nay (từ 0h) — đọc job in-memory trên server đang chạy.

Không có DB cho vote (in-memory) → chỉ đếm được nếu server đang chạy giữ jobs.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from datetime import datetime

sys.path.insert(0, ".")

BASE = "http://127.0.0.1:8083"


def _token() -> str:
    from db import get_engine

    engine = get_engine()
    try:
        with engine.get_connection() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = 'web.auth_token'"
            ).fetchone()
        if not row:
            return ""
        value = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        return value if isinstance(value, str) else ""
    finally:
        engine.close()


def main() -> None:
    token = _token()
    req = urllib.request.Request(
        BASE + "/api/vote/jobs",
        headers={"X-API-Token": token} if token else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except Exception as exc:  # noqa: BLE001
        print(f"Không đọc được jobs (server chưa chạy / token sai): {exc}")
        return

    now = time.time()
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_epoch = today_start.timestamp()

    jobs = data.get("jobs") or []
    today_succ = [
        j for j in jobs
        if j.get("status") == "success"
        and (j.get("finished_at") or 0) >= today_epoch
    ]
    total_succ = [j for j in jobs if j.get("status") == "success"]
    running = [j for j in jobs if j.get("status") == "running"]
    queued = [j for j in jobs if j.get("status") == "queued"]

    print(f"Thời điểm check: {datetime.now().strftime('%H:%M:%S %d/%m/%Y')}")
    print(f"Jobs trong session server: {len(jobs)}")
    print(f"  → SUCCESS hôm nay (từ 0h): {len(today_succ)}")
    print(f"  → SUCCESS cả session: {len(total_succ)}")
    print(f"  → running: {len(running)} · queued: {len(queued)}")
    if today_succ:
        print("Chi tiết hôm nay:")
        for j in today_succ[:20]:
            ts = datetime.fromtimestamp(j.get("finished_at") or 0).strftime("%H:%M")
            vr = j.get("vote_result") or {}
            print(f"  {ts}  {j.get('email')}  {vr.get('product','')} +{vr.get('point',0)}đ")
        if len(today_succ) > 20:
            print(f"  ... còn {len(today_succ) - 20} job nữa")


if __name__ == "__main__":
    main()