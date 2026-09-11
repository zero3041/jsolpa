"""Submit combo Eventista qua API (combo đọc từ stdin — không hardcode trong file)."""
import json
import sys
import urllib.request

COMBO = sys.stdin.read().strip()
TOKEN = "0SBif9J9HUAPpntVuatCXgLVTqv5iGCS"
URL = "http://127.0.0.1:8083/api/eventista/jobs"

payload = json.dumps({"combos": COMBO}).encode()
req = urllib.request.Request(
    URL, data=payload, method="POST",
    headers={"X-API-Token": TOKEN, "Content-Type": "application/json"},
)
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    print(f"added={data.get('added')}")
    for j in data.get("jobs", []):
        print(f"job_id={j.get('id')} status={j.get('status')}")
except Exception as exc:  # noqa: BLE001
    print(f"FAIL: {exc}")
    sys.exit(1)