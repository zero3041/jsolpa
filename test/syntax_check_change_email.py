"""AST parse các file chạm trong feature Đổi Email (không execute import).

Chạy:
    .venv/bin/python test/syntax_check_change_email.py
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_TARGETS: tuple[Path, ...] = (
    ROOT / "web" / "change_email.py",
    ROOT / "web" / "eventista.py",
    ROOT / "web" / "vote.py",
    ROOT / "web" / "sse_mux.py",
    ROOT / "web" / "server.py",
    ROOT / "db" / "repositories.py",
    ROOT / "test" / "check_change_email.py",
)


def main() -> int:
    failures: list[str] = []
    for path in _TARGETS:
        if not path.exists():
            failures.append(f"MISSING: {path}")
            print(f"[FAIL] {path.relative_to(ROOT)} — file not found", flush=True)
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            print(f"[PASS] {path.relative_to(ROOT)}", flush=True)
        except SyntaxError as exc:
            failures.append(f"{path}: line {exc.lineno}: {exc.msg}")
            print(
                f"[FAIL] {path.relative_to(ROOT)} — SyntaxError line {exc.lineno}: {exc.msg}",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{path}: {type(exc).__name__}: {exc}")
            print(
                f"[FAIL] {path.relative_to(ROOT)} — {type(exc).__name__}: {exc}",
                flush=True,
            )

    print(flush=True)
    if failures:
        print(f"=== SYNTAX CHECK FAILED ({len(failures)}/{len(_TARGETS)}) ===", flush=True)
        for f in failures:
            print(f"  - {f}", flush=True)
        return 1
    print(f"=== SYNTAX CHECK PASSED ({len(_TARGETS)} files) ===", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())