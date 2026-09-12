"""Check: module web/change_email + wiring server/settings.

Verify:
  1. Import web.change_email + web.server (mọi route đăng ký OK).
  2. _parse_account (email|password, email<TAB>password) + mailbox OutlookCombo.
  3. ChangeEmailManager API surface + apply_settings hydrate.
  4. add_jobs ghép cặp account+mailbox, skip đã dùng/đang chạy, không leak secret.
  5. list_outputs format `mailcu|mailmoi|pass`.
  6. Route /api/change-email/* được đăng ký.
  7. Settings whitelist + type constraint cho change_email.* (kể cả used_*).
  8. eventista._solve_turnstile hỗ trợ site_url/container_selector (backward-compat).

Lưu ý: check dùng subclass tắt worker queue — worker thật sẽ chạy job (launch
browser) nếu để nguyên, làm check không xác định.
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")

from web.change_email import (  # noqa: E402
    ChangeEmailError,
    ChangeEmailJob,
    ChangeEmailManager,
    _parse_account,
    _parse_mailbox,
)

_MAILBOX = (
    "cynthis.aguar@outlook.com|AP91091A"
    "|M.C548_BL2.0.U.-CqgdCzt95*gOD0DI6toKh3x9q66AboZafyIfJb7WejRno4NOdqrlH6d"
    "|9e5f94bc-e8a4-4e73-b8be-63364c29d753"
)
_MAILBOX2 = (
    "tfranciscan69@outlook.com|1z000036724a3593"
    "|M.C516_BL2.0.U.-CriLIZ7jvVk6zsGRarLMY"
    "|9e5f94bc-e8a4-4e73-b8be-63364c29d753"
)


class _CfgOnlyManager(ChangeEmailManager):
    """Manager không spawn worker — chỉ dùng cho check cấu hình/pairing."""

    def _ensure_workers(self) -> None:  # noqa: D102
        pass


async def _check_reject_marks_mailbox() -> None:
    """Lỗi "đã được sử dụng" → mailbox bị đánh dấu used, account thì không."""
    from web.change_email import ChangeEmailError, ChangeEmailJob

    cm = _CfgOnlyManager()
    cm._persist_used = lambda: None  # tránh ghi settings thật
    cm._repo = lambda: type("R", (), {"upsert": lambda *a, **k: None})()
    cm._use_proxy = False

    jid = "rej-test"
    job = ChangeEmailJob(
        id=jid,
        old_email="rej_acc@outlook.com",
        new_email="rej_mb@hotmail.com",
        _old_password="pw",
        _new_password="mpw",
        _refresh_token="M.C111_BAY.0.U.-x",
        _client_id="9e5f94bc-e8a4-4e73-b8be-63364c29d753",
    )
    cm.jobs[jid] = job
    cm.order.append(jid)

    async def _reject(job, *, proxy):
        raise ChangeEmailError("yêu cầu đổi email bị chặn: 'đã được sử dụng'")

    cm._run_job_inner = _reject  # type: ignore[method-assign]
    await cm._run_job(job)
    assert job.status == "error", job.status
    assert "rej_mb@hotmail.com" in cm.used_mailboxes, cm.used_mailboxes
    assert "rej_acc@outlook.com" not in cm.used_accounts, cm.used_accounts
    assert any("đánh dấu đã dùng" in line for line in job.log_lines), job.log_lines

    # Lỗi khác (vd login fail) KHÔNG đánh dấu mailbox
    cm2 = _CfgOnlyManager()
    cm2._persist_used = lambda: None
    cm2._repo = lambda: type("R", (), {"upsert": lambda *a, **k: None})()
    cm2._use_proxy = False
    job2 = ChangeEmailJob(
        id="rej-test-2", old_email="a2@outlook.com", new_email="m2@hotmail.com",
        _old_password="pw", _new_password="mpw",
        _refresh_token="M.C111_BAY.0.U.-x",
        _client_id="9e5f94bc-e8a4-4e73-b8be-63364c29d753",
    )
    cm2.jobs[job2.id] = job2
    cm2.order.append(job2)

    async def _login_fail(job, *, proxy):
        raise ChangeEmailError("không xác nhận được đăng nhập sau 30s")

    cm2._run_job_inner = _login_fail  # type: ignore[method-assign]
    await cm2._run_job(job2)
    # Auto-retry (transient, không fatal) requeue về queued — KHÔNG đánh dấu mailbox.
    assert job2.status in ("error", "queued"), job2.status
    assert "m2@hotmail.com" not in cm2.used_mailboxes, cm2.used_mailboxes


def main() -> None:
    # 1a. Parse account — pipe format
    email, pw = _parse_account("riadaoon+4@outlook.com|Vote@sol")
    assert email == "riadaoon+4@outlook.com" and pw == "Vote@sol", (email, pw)

    # 1b. Parse account — TAB format (bảng dán từ spreadsheet)
    email, pw = _parse_account("riadaoon+5@outlook.com\tVote@sol")
    assert email == "riadaoon+5@outlook.com" and pw == "Vote@sol", (email, pw)

    # 1c. Parse account fail
    for bad in ("", "không-có-@", "  "):
        try:
            _parse_account(bad)
        except ChangeEmailError:
            pass
        else:
            raise AssertionError(f"parse account phải fail: {bad!r}")

    # 1d. Parse mailbox (OutlookCombo 4 phần)
    combo = _parse_mailbox(_MAILBOX)
    assert combo.email == "cynthis.aguar@outlook.com"
    assert combo.refresh_token.startswith("M.C")

    # 2. Manager API surface
    cm = _CfgOnlyManager()
    for method in (
        "apply_settings", "to_config_dict", "add_jobs", "stop_all",
        "clear_finished", "clear_all", "retry_failed", "retry_job",
        "cancel_job", "remove_job", "get_job", "list_jobs", "list_outputs",
        "clear_used",
    ):
        assert callable(getattr(cm, method, None)), f"thiếu {method}"
    assert isinstance(cm.used_accounts, list)
    assert isinstance(cm.used_mailboxes, list)

    cfg = cm.to_config_dict()
    for key in (
        "max_concurrent", "job_timeout", "engine", "headless",
        "use_proxy", "candidate", "category", "captcha_mode",
        "poll_timeout_seconds", "yescaptcha_key", "min_seconds",
        "used_accounts", "used_mailboxes",
    ):
        assert key in cfg, f"config thiếu {key}"

    # 3. apply_settings hydrate
    cm.apply_settings({
        "change_email.engine": "chrome",
        "change_email.headless": True,
        "change_email.use_proxy": False,
        "change_email.max_concurrent": 2,
        "change_email.job_timeout": 300.0,
        "change_email.candidate": "Xoay Vòng",
        "change_email.category": "THE GROUP PERFORMANCE ICON",
        "change_email.captcha_mode": "inpage",
        "change_email.poll_timeout_seconds": 120.0,
        "change_email.min_seconds": 30.0,
        "change_email.used_accounts": ["a@b.com"],
        "change_email.used_mailboxes": ["x@y.com"],
    })
    cfg = cm.to_config_dict()
    assert cfg["engine"] == "chrome"
    assert cfg["headless"] is True
    assert cfg["use_proxy"] is False
    assert cfg["max_concurrent"] == 2
    assert cfg["job_timeout"] == 300.0
    assert cfg["candidate"] == "Xoay Vòng"
    assert cfg["captcha_mode"] == "inpage"
    assert cfg["poll_timeout_seconds"] == 120.0
    assert cfg["min_seconds"] == 30.0
    assert cfg["used_accounts"] == ["a@b.com"]
    assert cfg["used_mailboxes"] == ["x@y.com"]

    # 4. add_jobs ghép cặp + không leak secret
    jobs, skipped = cm.add_jobs(
        ["riadaoon+4@outlook.com|Vote@sol", "riadaoon+5@outlook.com|Vote@sol"],
        [_MAILBOX, _MAILBOX2],
    )
    assert len(jobs) == 2, jobs
    assert skipped == [], skipped
    job: ChangeEmailJob = cm.jobs[jobs[0].id]
    assert job.old_email == "riadaoon+4@outlook.com"
    assert job.new_email == "cynthis.aguar@outlook.com"
    assert job._old_password == "Vote@sol"
    assert job._new_password == "AP91091A"
    assert job._refresh_token.startswith("M.C")
    d = job.to_dict()
    for leak_key in ("_old_password", "_new_password", "_refresh_token", "_client_id"):
        assert leak_key not in d, f"to_dict leak {leak_key}"
    assert "_refresh_token" not in cm.list_jobs()[0]

    # 4b. Skip account/mailbox đã dùng
    cm.jobs.clear()
    cm.order.clear()
    cm._used_accounts = {"riadaoon+4@outlook.com"}
    cm._used_mailboxes = {"cynthis.aguar@outlook.com"}
    jobs2, skipped2 = cm.add_jobs(
        ["riadaoon+4@outlook.com|Vote@sol", "riadaoon+6@outlook.com|Vote@sol"],
        [_MAILBOX, _MAILBOX2],
    )
    assert len(jobs2) == 1, jobs2
    assert jobs2[0].old_email == "riadaoon+6@outlook.com"
    assert jobs2[0].new_email == "tfranciscan69@outlook.com"
    assert sum("đã sử dụng" in s for s in skipped2) == 2, skipped2

    # 4c. Account nhiều hơn mailbox → skip "thiếu mailbox"
    cm.jobs.clear()
    cm.order.clear()
    cm._used_accounts = set()
    cm._used_mailboxes = set()
    jobs3, skipped3 = cm.add_jobs(
        ["riadaoon+7@outlook.com|Vote@sol", "riadaoon+8@outlook.com|Vote@sol"],
        [_MAILBOX2],
    )
    assert len(jobs3) == 1, jobs3
    assert any("thiếu mailbox" in s for s in skipped3), skipped3

    # 4d. Account/mailbox đang chạy (queued/running) → skip
    jobs4, skipped4 = cm.add_jobs(
        ["riadaoon+9@outlook.com|Vote@sol", "riadaoon+7@outlook.com|Vote@sol"],
        [_MAILBOX2],
    )
    assert len(jobs4) == 0, jobs4
    assert any("đang chạy" in s for s in skipped4), skipped4

    # 4e. cancel_job: queued → cancelled; job đã kết thúc → False
    jobs5, _ = cm.add_jobs(
        ["riadaoon+10@outlook.com|Vote@sol"], [_MAILBOX]
    )
    cjid = jobs5[0].id
    assert cm.cancel_job(cjid) is True
    assert cm.jobs[cjid].status == "cancelled"
    assert cm.cancel_job(cjid) is False  # đã cancelled — không huỷ lại
    assert cm.cancel_job("khong-ton-tai") is False

    # 4f. Mailbox bị site chặn ("đã được sử dụng") → tự mark mailbox đã dùng
    asyncio.run(_check_reject_marks_mailbox())

    # 5. list_outputs format mailcu|mailmoi|pass
    cm.jobs.clear()
    cm.order.clear()
    jobs5, _ = cm.add_jobs(
        ["riadaoon+4@outlook.com|Vote@sol"], [_MAILBOX]
    )
    jobs5[0].status = "success"
    out = cm.list_outputs()
    assert out["success"][0] == "riadaoon+4@outlook.com|cynthis.aguar@outlook.com|Vote@sol", out

    # 5b. DB migration v14 + ChangeEmailRepository
    from db.engine import DatabaseEngine
    from db.repositories import ChangeEmailRepository

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        engine = DatabaseEngine(db_path=str(db_path))
        try:
            with engine.get_connection() as conn:
                row = conn.execute(
                    "SELECT version FROM _schema_version ORDER BY version DESC LIMIT 1"
                ).fetchone()
                assert row is not None and row["version"] >= 14, row
                tables = [r["name"] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )]
                assert "change_email_jobs" in tables, "thiếu bảng change_email_jobs"

            repo = ChangeEmailRepository(engine)
            repo.upsert(
                "hist_test@outlook.com", "new_hist@hotmail.com",
                password="pw1", status="running", engine="camoufox",
            )
            repo.upsert(
                "hist_test@outlook.com", "new_hist@hotmail.com",
                status="success", activation_url="https://account.faniesta.com/v2/user/email-change/verify?token=x",
            )
            row = repo.get_by_email("hist_test@outlook.com")
            assert row is not None and row["status"] == "success", row
            assert row["new_email"] == "new_hist@hotmail.com"
            rows = repo.list_all()
            assert len(rows) == 1 and rows[0]["old_email"] == "hist_test@outlook.com"
            assert repo.delete("hist_test@outlook.com") is True
            assert repo.get_by_email("hist_test@outlook.com") is None
        finally:
            engine.close()

    # 5c. history route + list_history
    import web.server  # noqa: F401

    paths = {getattr(r, "path", "") for r in web.server.app.routes}
    assert "/api/change-email/history" in paths, "route history thiếu"

    # 6. web.server routes
    import web.server  # noqa: F401

    app = web.server.app
    paths = {getattr(r, "path", "") for r in app.routes}
    for expected in (
        "/api/change-email/jobs",
        "/api/change-email/jobs/stop-all",
        "/api/change-email/jobs/clear-finished",
        "/api/change-email/jobs/clear-all",
        "/api/change-email/jobs/retry-failed",
        "/api/change-email/outputs",
        "/api/change-email/used/clear",
        "/api/change-email/jobs/{job_id}",
        "/api/change-email/jobs/{job_id}/retry",
        "/api/change-email/jobs/{job_id}/cancel",
        "/api/change-email/config",
    ):
        assert expected in paths, f"route thiếu: {expected}"

    # 7. Settings whitelist + type constraint
    from db.repositories import (  # noqa: E402
        RepositoryError,
        _EXACT_KEYS,
        _SENSITIVE_KEYS,
        _validate_type_constraint,
    )

    for key in (
        "change_email.engine", "change_email.headless",
        "change_email.max_concurrent", "change_email.use_proxy",
        "change_email.job_timeout", "change_email.candidate",
        "change_email.category", "change_email.captcha_mode",
        "change_email.poll_timeout_seconds", "change_email.yescaptcha_key",
        "change_email.min_seconds",
        "change_email.used_accounts", "change_email.used_mailboxes",
    ):
        assert key in _EXACT_KEYS, f"settings whitelist thiếu {key}"
    assert "change_email.yescaptcha_key" in _SENSITIVE_KEYS

    _validate_type_constraint("change_email.engine", "camoufox")
    _validate_type_constraint("change_email.headless", True)
    _validate_type_constraint("change_email.max_concurrent", 1)
    _validate_type_constraint("change_email.captcha_mode", "inpage")
    _validate_type_constraint("change_email.min_seconds", 0)
    _validate_type_constraint("change_email.candidate", "Xoay Vòng")
    _validate_type_constraint("change_email.yescaptcha_key", None)
    _validate_type_constraint("change_email.used_accounts", ["a@b.com"])
    _validate_type_constraint("change_email.used_mailboxes", [])
    for bad_key, bad_val in (
        ("change_email.engine", "ie"),
        ("change_email.headless", 1),
        ("change_email.max_concurrent", 0),
        ("change_email.captcha_mode", "nope"),
        ("change_email.min_seconds", 500),
        ("change_email.candidate", "  "),
        ("change_email.used_accounts", "not-a-list"),
        ("change_email.used_mailboxes", [1, 2]),
    ):
        try:
            _validate_type_constraint(bad_key, bad_val)
        except RepositoryError:
            pass
        else:
            raise AssertionError(f"type constraint phải chặn: {bad_key}={bad_val!r}")

    # 8. eventista._solve_turnstile backward-compat signature
    import inspect

    from web.eventista import _solve_turnstile, _solve_turnstile_camoufox  # noqa: E402

    sig = inspect.signature(_solve_turnstile)
    assert "site_url" in sig.parameters and "container_selector" in sig.parameters
    assert sig.parameters["container_selector"].default == "#cf-turnstile"
    sig2 = inspect.signature(_solve_turnstile_camoufox)
    assert "container_selector" in sig2.parameters

    print("PASS: web.change_email + wiring OK")
    print(f"  output sample: {out['success'][0]}")


if __name__ == "__main__":
    main()