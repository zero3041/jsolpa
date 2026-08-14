"""Syntax + unit check cho Reg Eventista (web/eventista.py).

Chạy: .venv/bin/python test/check_eventista.py

Các check:
  1. AST parse web/eventista.py + web/server.py (route thêm đúng chỗ).
  2. generate_password() đủ 4 loại ký tự.
  3. _ACTIVATION_URL_RE trích link từ body mail HTML (kèm &amp;).
  4. EventistaManager.add_jobs: combo hợp lệ → queued; combo sai → error.
  5. EventistaManager.retry_failed / clear_finished.
  6. DB migration v13: bảng eventista_accounts + cột tag_eventista tồn tại.
"""
from __future__ import annotations

import ast
import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def check_syntax() -> bool:
    py_files = [
        ROOT / "web" / "eventista.py",
        ROOT / "web" / "server.py",
    ]
    ok = True
    for path in py_files:
        src = path.read_text(encoding="utf-8")
        try:
            ast.parse(src, filename=str(path))
            print(f"[PASS] AST parse — {path.relative_to(ROOT)}", flush=True)
        except SyntaxError as exc:
            print(f"[FAIL] syntax error {path}: {exc}", flush=True)
            ok = False

    js = ROOT / "web" / "static" / "eventista.js"
    if shutil.which("node"):
        from subprocess import run

        result = run(["node", "--check", str(js)], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"[PASS] node --check — {js.relative_to(ROOT)}", flush=True)
        else:
            print(f"[FAIL] node --check {js}: {result.stderr.strip()}", flush=True)
            ok = False
    else:
        print("[WARN] node không có — bỏ qua JS syntax check", flush=True)
    return ok


def check_password() -> bool:
    from web.eventista import generate_password

    pw = generate_password()
    checks = {
        "upper": any(c.isupper() for c in pw),
        "lower": any(c.islower() for c in pw),
        "digit": any(c.isdigit() for c in pw),
        "special": any(c in "!@#$%^&*" for c in pw),
        "length": len(pw) >= 14,
    }
    for name, passed in checks.items():
        print(f"[{'PASS' if passed else 'FAIL'}] password {name}", flush=True)
        if not passed:
            return False
    return True


def check_eventista_job_layout_and_captcha_mode() -> bool:
    """Eventista có 4 ô trong job row, nên cần grid riêng; mode camoufox phải lưu được."""
    from web.eventista import EventistaManager

    manager = EventistaManager()
    try:
        manager.set_captcha_mode("camoufox")
    except ValueError as exc:
        print(f"[FAIL] captcha mode camoufox bị từ chối: {exc}", flush=True)
        return False
    if manager.captcha_mode != "camoufox":
        print(f"[FAIL] captcha mode sai sau khi set: {manager.captcha_mode}", flush=True)
        return False

    js = (ROOT / "web" / "static" / "eventista.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "static" / "style.css").read_text(encoding="utf-8")
    html = (ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
    expected = "eventista-job"
    if expected not in js or "#tab-eventista .job.eventista-job" not in css:
        print("[FAIL] Job Eventista chưa có grid 4 cột riêng", flush=True)
        return False
    if "#tab-eventista .card-jobs .job-list" not in css or "overflow-y: scroll" not in css:
        print("[FAIL] Jobs Eventista chưa ép vùng cuộn dọc", flush=True)
        return False
    if "ev-btn-scroll-jobs" not in html or "jobList.scrollTo" not in js:
        print("[FAIL] Jobs Eventista chưa có nút cuộn xuống", flush=True)
        return False
    print("[PASS] Job Eventista dùng grid riêng + lưu được mode camoufox", flush=True)
    return True


def check_activation_regex() -> bool:
    from web.eventista import _ACTIVATION_URL_RE

    html = (
        '<a href="https://account.faniesta.com/v2/auth/accounts/verify-email'
        '?token=abc.def.ghi&amp;redirect_uri=https%3A%2F%2Ftinhhasayhi.1vote.vn'
        '%2Fvi%2Fauth%2Fverify-account%3FregisterStatus%3D1">Activate</a>'
    )
    match = _ACTIVATION_URL_RE.search(html)
    if not match:
        print("[FAIL] regex không trích được link kích hoạt", flush=True)
        return False
    link = match.group(0).replace("&amp;", "&")
    ok = "token=abc.def.ghi" in link and "redirect_uri" in link
    print(f"[{'PASS' if ok else 'FAIL'}] extract activation link: {link[:80]}...", flush=True)
    return ok


async def _async_manager_checks() -> bool:
    from web.eventista import EventistaManager

    em = EventistaManager(max_concurrent=2)

    # 1. Combo hợp lệ
    jobs = em.add_jobs([
        "test.one@hotmail.com|pass123|M.C548_testtoken_1|9e5f94bc-e8a4-4e73-b8be-63364c29d753",
        "test.two@outlook.com|pass456|M.C525_testtoken_2|8b4ba9dd-3ea5-4e5f-86f1-ddba2230dcf2",
        "badline-no-pipes",
    ])
    if len(jobs) != 3:
        print(f"[FAIL] add_jobs trả {len(jobs)} job (mong đợi 3)", flush=True)
        return False
    valid = [j for j in jobs if j.status == "queued"]
    errors = [j for j in jobs if j.status == "error"]
    if len(valid) != 2 or len(errors) != 1:
        print(f"[FAIL] valid={len(valid)}, error={len(errors)}", flush=True)
        return False
    print("[PASS] add_jobs: 2 queued + 1 error (format sai)", flush=True)

    # 2. Password random đúng + secret fields không leak qua to_dict
    job = valid[0]
    if not job.password:
        print("[FAIL] job.password rỗng", flush=True)
        return False
    d = job.to_dict()
    if "password" in d or "_refresh_token" in d or "_client_id" in d:
        print("[FAIL] to_dict() leak secret fields", flush=True)
        return False
    print("[PASS] to_dict() không leak password/token", flush=True)

    # 3. retry_failed + clear_finished
    await em.stop_all()
    retried = await em.retry_failed()
    if retried < 1:
        print(f"[FAIL] retry_failed={retried}", flush=True)
        return False
    print("[PASS] retry_failed requeue job", flush=True)

    em.clear_finished()
    running = [j for j in em.jobs.values() if j.status not in ("queued", "running")]
    if running:
        print("[FAIL] clear_finished còn job finished", flush=True)
        return False
    print("[PASS] clear_finished chỉ xoá job kết thúc", flush=True)

    # 4. clear_all xoá mọi status (kể cả queued/running)
    before = len(em.jobs)
    removed = em.clear_all()
    if removed != before or len(em.jobs) != 0:
        print(f"[FAIL] clear_all: removed={removed}, còn={len(em.jobs)}", flush=True)
        return False
    print(f"[PASS] clear_all xoá {removed} job (mọi status)", flush=True)

    # 5. list_outputs: success → email|password; error → email → error
    j1 = em.add_jobs([
        "out.one@hotmail.com|pw111|M.C548_tok|9e5f94bc-e8a4-4e73-b8be-63364c29d753",
    ])[0]
    j1.status = "success"
    j1.finished_at = 1.0
    j2 = em.add_jobs([
        "out.two@outlook.com|pw222|M.C525_tok|8b4ba9dd-3ea5-4e5f-86f1-ddba2230dcf2",
    ])[0]
    j2.status = "error"
    j2.error = "Turnstile fail"
    outs = em.list_outputs()
    if outs["success"] != [f"out.one@hotmail.com|{j1.password}|no_2fa"]:
        print(f"[FAIL] list_outputs success: {outs['success']}", flush=True)
        return False
    if outs["errors"] != ["out.two@outlook.com  →  Turnstile fail"]:
        print(f"[FAIL] list_outputs errors: {outs['errors']}", flush=True)
        return False
    print("[PASS] list_outputs success/error đúng định dạng", flush=True)
    return True


def check_manager() -> bool:
    return asyncio.run(_async_manager_checks())


def check_db_migration() -> bool:
    from db.engine import DatabaseEngine

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        engine = DatabaseEngine(db_path=str(db_path))
        try:
            with engine.get_connection() as conn:
                row = conn.execute(
                    "SELECT version FROM _schema_version ORDER BY version DESC LIMIT 1"
                ).fetchone()
                if row is None or row["version"] < 13:
                    print(f"[FAIL] schema version = {row}", flush=True)
                    return False
                print(f"[PASS] schema version = {row['version']}", flush=True)

                cols = [r["name"] for r in conn.execute("PRAGMA table_info(outlook_combos)")]
                if "tag_eventista" not in cols:
                    print("[FAIL] outlook_combos thiếu cột tag_eventista", flush=True)
                    return False
                print("[PASS] outlook_combos.tag_eventista tồn tại", flush=True)

                tables = [r["name"] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )]
                if "eventista_accounts" not in tables:
                    print("[FAIL] bảng eventista_accounts không tồn tại", flush=True)
                    return False
                print("[PASS] bảng eventista_accounts tồn tại", flush=True)

            # ── Repo ops — NGOÀI `with get_connection()` (nested tx không commit,
            #    còn read connection (raw_connection) là connection riêng) ──
            # EventistaAccountRepository upsert/update/list
            from db.repositories import EventistaAccountRepository

            repo = EventistaAccountRepository(engine)
            repo.upsert(
                "repo.test@hotmail.com", "pw123",
                status="registering", engine="camoufox",
            )
            repo.update_status("repo.test@hotmail.com", "activated", activation_url="https://x")
            rows = repo.list_all()
            if len(rows) != 1 or rows[0]["status"] != "activated":
                print(f"[FAIL] repository roundtrip: {rows}", flush=True)
                return False
            print("[PASS] EventistaAccountRepository upsert/update/list OK", flush=True)

            # ComboRepository list_untagged_eventista + mark_eventista_used
            from db.repositories import ComboRepository

            cr = ComboRepository(engine)
            cr.upsert({
                "email": "combo.repo@hotmail.com",
                "password": "pw",
                "refresh_token": "M.Ctest",
                "client_id": "9e5f94bc-e8a4-4e73-b8be-63364c29d753",
            })
            untagged = cr.list_untagged_eventista()
            if not any(c["email"] == "combo.repo@hotmail.com" for c in untagged):
                print("[FAIL] list_untagged_eventista thiếu combo mới", flush=True)
                return False
            cr.mark_eventista_used("combo.repo@hotmail.com")
            untagged2 = cr.list_untagged_eventista()
            if any(c["email"] == "combo.repo@hotmail.com" for c in untagged2):
                print("[FAIL] mark_eventista_used không tag", flush=True)
                return False
            print("[PASS] ComboRepository eventista tag OK", flush=True)
        finally:
            engine.close()
    return True


def check_settings_keys() -> bool:
    from db.repositories import SettingsRepository, _EXACT_KEYS, RepositoryError

    expected = {
        "eventista.engine", "eventista.headless", "eventista.default_password",
        "eventista.max_concurrent", "eventista.use_proxy", "eventista.captcha_mode",
        "eventista.poll_timeout_seconds", "eventista.job_timeout",
        "eventista.yescaptcha_key",
    }
    missing = expected - set(_EXACT_KEYS)
    if missing:
        print(f"[FAIL] _EXACT_KEYS thiếu: {sorted(missing)}", flush=True)
        return False
    print("[PASS] eventista.* keys trong _EXACT_KEYS", flush=True)

    with tempfile.TemporaryDirectory() as tmp:
        from db.engine import DatabaseEngine

        engine = DatabaseEngine(db_path=str(Path(tmp) / "s.db"))
        try:
            repo = SettingsRepository(engine)
            # Valid: engine + captcha_mode (auto/click/yescaptcha) + max_concurrent (int)
            repo.bulk_set({
                "eventista.engine": "playwright",
                "eventista.captcha_mode": "yescaptcha",
                "eventista.max_concurrent": 5,
            })
            for mode in ("auto", "click", "none"):
                repo.set("eventista.captcha_mode", mode)
            # Invalid: sai enum → RepositoryError
            try:
                repo.set("eventista.engine", "firefox")
                print("[FAIL] eventista.engine nhận giá trị không hợp lệ", flush=True)
                return False
            except RepositoryError:
                pass
            try:
                repo.set("eventista.max_concurrent", "5")  # string, không phải int
                print("[FAIL] max_concurrent nhận string", flush=True)
                return False
            except RepositoryError:
                pass
            try:
                repo.set("eventista.captcha_mode", "hack")
                print("[FAIL] captcha_mode nhận giá trị không hợp lệ", flush=True)
                return False
            except RepositoryError:
                pass
            print("[PASS] Settings validation eventista.* OK", flush=True)
        finally:
            engine.close()
    return True


def main() -> int:
    os.environ.setdefault("GSH_DB_PATH", ":memory:")
    checks = [
        ("syntax", check_syntax),
        ("password", check_password),
        ("activation regex", check_activation_regex),
        ("Eventista job layout + captcha mode", check_eventista_job_layout_and_captcha_mode),
        ("manager", check_manager),
        ("db migration v13", check_db_migration),
        ("settings keys", check_settings_keys),
    ]
    failed = 0
    for name, fn in checks:
        try:
            ok = fn()
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] {name}: {type(exc).__name__}: {exc}", flush=True)
            ok = False
        if not ok:
            failed += 1
        print(f"── {name}: {'OK' if ok else 'FAIL'} ──", flush=True)
    if failed:
        print(f"[RESULT] {failed}/{len(checks)} check fail", flush=True)
        return 1
    print("[RESULT] all checks ok", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
