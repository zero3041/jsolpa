"""Export lịch sử Đổi Email thành công — STANDALONE, chạy được trên máy bất kỳ.

CHỈ cần 2 thứ: Python (bản thường, không cần pip gì) + file data.db.

Cách dùng:
    python export_change_email_success.py [duong-dan-data.db] [prefix_lọc]

  - Không truyền gì: mặc định đọc runtime/data.db (chạy ngay trong thư mục repo).
  - Truyền 1 tham số: đường dẫn file DB khác.
  - Truyền 2 tham số: thêm prefix lọc email cũ (vd "concuudenn").

Output: <thư mục chứa DB>/change_email_success.txt
Format mỗi dòng (pipe-separated):
    old_email|new_email|password
vd: concuudenn+61@gmail.com|celinehqxartmann4687516798@outlook.com|Vote@sol
"""
from __future__ import annotations

import sqlite3
import sys
from collections import Counter
from pathlib import Path


def main() -> None:
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("runtime/data.db")
    prefix = sys.argv[2] if len(sys.argv) > 2 else None

    if not db_path.exists():
        print(f"KHÔNG tìm thấy DB: {db_path}")
        raise SystemExit(1)

    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT old_email, new_email, password, updated_at "
            "FROM change_email_jobs WHERE status = 'success' "
            "ORDER BY updated_at DESC"
        ).fetchall()
    finally:
        conn.close()

    all_rows = list(rows)
    if prefix:
        all_rows = [r for r in all_rows if r[0].lower().startswith(prefix.lower())]

    print(f"Tổng success: {len(rows)}")
    if prefix:
        print(f"Khớp prefix '{prefix}': {len(all_rows)}")
    if rows:
        counts = Counter(
            r[0].split("+")[0] if "+" in r[0] else r[0] for r in rows
        )
        print("Phân bố theo prefix email cũ:")
        for k, v in counts.most_common(20):
            print(f"  {k}* : {v}")

    out_file = db_path.parent / "change_email_success.txt"
    with out_file.open("w", newline="", encoding="utf-8-sig") as f:
        for old, new, pwd, _ts in all_rows:
            f.write(f"{old}|{new}|{pwd}\n")
    print(f"Đã export {len(all_rows)} dòng → {out_file.resolve()}")

    if all_rows:
        print("Preview 5 dòng:")
        for r in all_rows[:5]:
            print(f"  {r[0]}|{r[1]}|{r[2]}")


if __name__ == "__main__":
    main()