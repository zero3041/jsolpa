"""Smoke test: web server import + settings whitelist mail_reader.max_messages.

Chạy: .venv/bin/python test/smoke_imports_mail_reader.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


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

    ok &= _check("import web.mail_reader", lambda: __import__("web.mail_reader"))
    ok &= _check(
        "import web.server (routes đăng ký)",
        lambda: __import__("web.server"),
    )

    def _route_exists():
        import web.server as server_mod
        paths = {r.path for r in server_mod.app.routes}
        assert "/api/mail-reader/check" in paths, "missing /api/mail-reader/check route"
    ok &= _check("route /api/mail-reader/check", _route_exists)

    def _settings_whitelist():
        from db.repositories import _EXACT_KEYS
        assert "mail_reader.max_messages" in _EXACT_KEYS, "missing whitelist key"
    ok &= _check("settings whitelist key", _settings_whitelist)

    def _settings_type_ok():
        from db.repositories import SettingsRepository, _validate_type_constraint
        _validate_type_constraint("mail_reader.max_messages", 10)      # hợp lệ
        try:
            _validate_type_constraint("mail_reader.max_messages", 0)   # out of range
            raise AssertionError("0 phải bị reject")
        except Exception:
            pass
        try:
            _validate_type_constraint("mail_reader.max_messages", "10")  # sai type
            raise AssertionError("string phải bị reject")
        except Exception:
            pass
    ok &= _check("settings type constraint", _settings_type_ok)

    print("ALL OK" if ok else "HAS FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())