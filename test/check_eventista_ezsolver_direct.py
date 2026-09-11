"""Verify: solver.py trực tiếp với proxy — in "using proxy" + token.

Chạy thẳng hàm solve của EzSolver (không qua service) để xác nhận
proxy được truyền vào create_context của nodriver.
"""
import sys
from pathlib import Path

sys.path.insert(0, "/home/push/tools/EzSolver")

from solver import solve  # noqa: E402

PROXY = "http://christopher1398:nzgwnde0ndi4mzg=@103.216.74.218:4604"

token = solve(
    "0x4AAAAAACzQ71rtjbtFwyuA",
    "https://tinhhasayhi.1vote.vn/",
    timeout=100,
    proxy=PROXY,
)
print(f"token OK ({len(token)} ký tự, bắt đầu bằng {token[:4]!r})")