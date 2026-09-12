"""Export lịch sử Đổi Email thành công từ DB.

Format mỗi dòng (pipe-separated):
    old_email|new_email|password
đúng format concuudenn+22@gmail.com|borisschumdlz2336760@outlook.com|Vote@sol.

Output: runtime/change_email_success.txt (UTF-8 BOM — Excel mở không lỗi tiếng Việt).
Chạy: .venv\\Scripts\\python test\\export_change_email_success.py [prefix_filter]
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, ".")

from db import get_engine  # noqa: E402

OUT_FILE = Path("runtime") / "change_email_success.txt"


def main() -> None:
    prefix = sys.argv[1] if len(sys.argv) > 1 else None
    engine = get_engine()

    with engine.get_connection() as conn:
        rows = conn.execute(
            "SELECT old_email, new_email, password, updated_at "
            "FROM change_email_jobs WHERE status = 'success' "
            "ORDER BY updated_at DESC"
        ).fetchall()

    engine.close()

    all_rows = [dict(r) for r in rows]
    if prefix:
        all_rows = [r for r in all_rows if r["old_email"].lower().startswith(prefix.lower())]

    print(f"Tổng success: {len(rows)}")
    if prefix:
        print(f"Khớp prefix '{prefix}': {len(all_rows)}")
    if rows:
        from collections import Counter

        counts = Counter(r["old_email"].split("+")[0] if "+" in r["old_email"] else r["old_email"] for r in rows)
        print("Phân bố theo prefix email cũ:")
        for k, v in counts.most_common(20):
            print(f"  {k}* : {v}")

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OUT_FILE.open("w", newline="", encoding="utf-8-sig") as f:
        for r in all_rows:
            f.write(f"{r['old_email']}|{r['new_email']}|{r['password']}\n")
    print(f"Đã export {len(all_rows)} dòng → {OUT_FILE.resolve()}")

    if all_rows:
        print("Preview 5 dòng:")
        for r in all_rows[:5]:
            print(f"  {r['old_email']}|{r['new_email']}|{r['password']}")


if __name__ == "__main__":
    main()