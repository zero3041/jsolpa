"""Submit 1 job Auto Vote dry-run (confirm_vote=false — không bấm vote thật)."""
from __future__ import annotations

import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8083"
TOKEN = "0SBif9J9HUAPpntVuatCXgLVTqv5iGCS"


def _post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode(),
        headers={
            "X-API-Token": TOKEN,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def main() -> None:
    combos = sys.stdin.read().strip()
    if not combos:
        print("stdin rỗng — không submit")
        return
    res = _post("/api/vote/jobs", {"combos": combos})
    print(f"added={res['added']}")
    for job in res["jobs"]:
        print(f"  {job['id']}  {job['email']}  {job['status']}")


if __name__ == "__main__":
    main()
