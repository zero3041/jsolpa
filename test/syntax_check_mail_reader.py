"""Syntax check cho tính năng Đọc Hòm Thư (mail_reader).

Chạy: python3 test/syntax_check_mail_reader.py
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FILES = [
    "web/mail_reader.py",
    "web/server.py",
    "db/repositories.py",
]

JS_FILES = [
    "web/static/mailreader.js",
]


def _check(name, fn):
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] {name}: {type(exc).__name__}: {exc}")
        return False
    print(f"[OK]   {name}")
    return True


def main() -> int:
    ok = True
    for rel in FILES:
        path = ROOT / rel
        ok &= _check(f"ast {rel}", lambda p=path: ast.parse(p.read_text(encoding="utf-8")))
    for rel in JS_FILES:
        path = ROOT / rel
        ok &= _check(f"exists {rel}", lambda p=path: p.read_text(encoding="utf-8"))
    # Node check nếu có node
    for rel in JS_FILES:
        path = ROOT / rel
        ok &= _check(
            f"node --check {rel}",
            lambda p=path: _node_check(p),
        )
    print("ALL OK" if ok else "HAS FAILURES")
    return 0 if ok else 1


def _node_check(path: Path) -> None:
    import subprocess

    result = subprocess.run(
        ["node", "--check", str(path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())


if __name__ == "__main__":
    sys.exit(main())
