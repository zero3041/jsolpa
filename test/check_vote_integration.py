"""Smoke: import web.server (kích hoạt mọi route + boot path) và web.vote.

Verify các route /api/vote/* được đăng ký, config dict khớp API contract
của server.py và vote.js.
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, ".")

from web.vote import (  # noqa: E402
    AlreadyVotedError,
    VoteError,
    VoteJob,
    VoteManager,
    _build_vote_result,
    _decode_vote_extra,
    _format_vote_result,
    _parse_combo,
    get_vote_manager,
)

# extraData base64 thật từ response voting-free (job Xoay Vòng)
_SAMPLE_EXTRA = (
    "eyJ0ZW5hbnRJZCI6Ik9RQUdsMCIsInRlbmFudE5hbWUiOiJUaW5oIEhhIFNheSBIaSIsImRvbWFpbiI6"
    "Imh0dHBzOi8vdGluaGhhc2F5aGkuMXZvdGUudm4iLCJldmVudCI6eyJpZCI6IkVWRU5UX0JYVGh1Iiwibm"
    "FtZSI6IlRIRSBHUk9VUCBQRVJGT1JNQU5DRSBJQ09OIn0sInByb2R1Y3QiOnsiaWQiOiJmMHh3IiwicHJv"
    "ZHVjdEdyb3VwSWQiOiJ5NEtXdSIsIm5hbWUiOiJYb2F5IFZvbmcifSwicG9pbnRQYWNrYWdlIjp7InBv"
    "aW50IjoxLCJhbW91bnQiOjB9LCJwcm9tb3Rpb24iOiJuL2EiLCJwYXltZW50RGF0ZSI6IjEyLzA5LzIw"
    "MjYgMjA6MTI6MzkiLCJpcEFkZHJlc3MiOiIyNDA1OjQ4MDI6Yzc3Ojk3ZTA6MTk0MDozMjAxOjJiOTU6"
    "MWJhYyIsImN1cnJlbnRfcG9pbnQiOjMyMDczLCJ0b3RhbF9wb2ludCI6MzIwNzR9"
)


def main() -> None:
    # 1. Parse combo
    email, pw = _parse_combo("taolaban007@gmail.com|Bss123@#")
    assert email == "taolaban007@gmail.com" and pw == "Bss123@#", (email, pw)

    # 1b. Decode extraData từ response voting-free thật
    info = _decode_vote_extra(_SAMPLE_EXTRA)
    assert (info.get("product") or {}).get("name") == "Xoay Vong", info
    assert info.get("current_point") == 32073, info
    assert info.get("total_point") == 32074, info
    assert (info.get("pointPackage") or {}).get("point") == 1, info
    assert (info.get("event") or {}).get("name") == "THE GROUP PERFORMANCE ICON", info

    # 1c. _build_vote_result với body response đầy đủ
    body = {
        "errorCode": 0,
        "message": "OK",
        "data": {
            "message": "Bình chọn thành công",
            "orderId": "s6NlEgboUzml",
            "extraData": _SAMPLE_EXTRA,
            "remainingFreeVotes": 0,
            "nextVoteTime": "2026-09-12T17:00:00.000Z",
            "nextVoteInSeconds": 13640,
        },
    }
    vr = _build_vote_result(body)
    assert vr["product"] == "Xoay Vong", vr
    assert vr["point"] == 1, vr
    assert vr["current_point"] == 32073, vr
    assert vr["total_point"] == 32074, vr
    assert vr["remaining_free_votes"] == 0, vr
    assert vr["next_vote_in_seconds"] == 13640, vr
    summary = _format_vote_result(vr)
    assert "Xoay Vong" in summary and "32074" in summary and "0 lượt free" in summary, summary

    # 1d. _decode_vote_extra chịu được input rác
    assert _decode_vote_extra("") == {}
    assert _decode_vote_extra("###không-phải-base64###") == {}

    # 2. VoteManager API surface mà server.py gọi
    vm = VoteManager()
    for method in (
        "apply_settings", "to_config_dict", "add_jobs", "stop_all",
        "clear_finished", "clear_all", "retry_failed", "retry_job",
        "remove_job", "get_job", "list_jobs", "list_outputs",
    ):
        assert callable(getattr(vm, method, None)), f"thiếu {method}"

    cfg = vm.to_config_dict()
    for key in (
        "max_concurrent", "job_timeout", "engine", "headless",
        "use_proxy", "candidate", "category", "confirm_vote",
    ):
        assert key in cfg, f"config thiếu {key}"

    # 3. apply_settings hydrate
    vm.apply_settings({
        "vote.engine": "chrome",
        "vote.headless": True,
        "vote.use_proxy": False,
        "vote.max_concurrent": 2,
        "vote.job_timeout": 300.0,
        "vote.candidate": "Anh Trai JSOL",
        "vote.category": "THE GROUP PERFORMANCE ICON",
        "vote.confirm_vote": True,
    })
    cfg = vm.to_config_dict()
    assert cfg["engine"] == "chrome"
    assert cfg["headless"] is True
    assert cfg["use_proxy"] is False
    assert cfg["max_concurrent"] == 2
    assert cfg["job_timeout"] == 300.0
    assert cfg["candidate"] == "Anh Trai JSOL"
    assert cfg["category"] == "THE GROUP PERFORMANCE ICON"
    assert cfg["confirm_vote"] is True

    # 3b. set_category: rỗng = skip tab (giữ flow cũ)
    vm.set_category("")
    assert vm.category == ""
    vm.set_category("  OTHER TAB  ")
    assert vm.category == "OTHER TAB"

    # 3c. Settings whitelist + type constraint cho vote.category
    from db.repositories import _EXACT_KEYS, _validate_type_constraint

    assert "vote.category" in _EXACT_KEYS, "settings whitelist thiếu vote.category"
    _validate_type_constraint("vote.category", "THE GROUP PERFORMANCE ICON")
    _validate_type_constraint("vote.category", "")

    # 3d. Daily skip: account đã vote success hôm nay → error job, không vào queue
    class _NoWorkerVoteManager(VoteManager):
        def _ensure_workers(self) -> None:
            pass

    vm2 = _NoWorkerVoteManager()
    vm2._vote_repo = lambda: type("R", (), {
        "success_emails_since": lambda self, iso: {"votedtoday@outlook.com"},
        "upsert": lambda *a, **k: None,
        "list_all": lambda *a, **k: [],
    })()
    jobs2 = vm2.add_jobs([
        "votedtoday@outlook.com|pw1",
        "freshtoday@outlook.com|pw2",
    ])
    assert len(jobs2) == 2, jobs2
    by_email = {j.email: j for j in jobs2}
    assert by_email["votedtoday@outlook.com"].status == "error"
    assert "đã vote" in (by_email["votedtoday@outlook.com"].error or "")
    assert by_email["freshtoday@outlook.com"].status == "queued"

    # 3e. AlreadyVotedError → success (không retry); VoteError transient → auto-retry
    asyncio.run(_check_runner_paths())

    print("PASS: web.vote + web.server routes OK")
    print(f"  config: {cfg}")

    # 4. Import web.server → mọi route đăng ký OK (no import error)
    import web.server  # noqa: F401

    app = web.server.app
    paths = {getattr(r, "path", "") for r in app.routes}
    for expected in (
        "/api/vote/jobs",
        "/api/vote/jobs/stop-all",
        "/api/vote/jobs/clear-finished",
        "/api/vote/jobs/clear-all",
        "/api/vote/jobs/retry-failed",
        "/api/vote/outputs",
        "/api/vote/history",
        "/api/vote/jobs/{job_id}",
        "/api/vote/jobs/{job_id}/retry",
        "/api/vote/config",
    ):
        assert expected in paths, f"route thiếu: {expected}"


async def _check_runner_paths() -> None:
    from web.vote import AlreadyVotedError, VoteError, VoteJob, VoteManager

    class _NoWorker(VoteManager):
        def _ensure_workers(self) -> None:
            pass

    def _mk_cm() -> _NoWorker:
        cm = _NoWorker()
        cm._use_proxy = False
        cm._vote_repo = lambda: type("R", (), {
            "upsert": lambda *a, **k: None,
            "list_all": lambda *a, **k: [],
        })()
        return cm

    # AlreadyVotedError → success
    cm = _mk_cm()
    job = VoteJob(id="a1", email="a@outlook.com", _password="pw")
    cm.jobs[job.id] = job
    cm.order.append(job.id)

    async def _already(job, *, proxy):
        raise AlreadyVotedError("đã vote hôm nay — Cập nhật sau 05:37:40")

    cm._run_job_inner = _already  # type: ignore[method-assign]
    await cm._run_job(job)
    assert job.status == "success", job.status
    assert job.retry_count == 0, job.retry_count

    # VoteError transient (video timeout) → auto-retry requeue
    cm2 = _mk_cm()
    job2 = VoteJob(id="a2", email="b@outlook.com", _password="pw")
    cm2.jobs[job2.id] = job2
    cm2.order.append(job2.id)

    async def _video_fail(job, *, proxy):
        raise VoteError("video không hoàn thành trong 60s")

    cm2._run_job_inner = _video_fail  # type: ignore[method-assign]
    await cm2._run_job(job2)
    assert job2.status == "queued", job2.status
    assert job2.retry_count == 1, job2.retry_count
    assert "auto-retry" in "\n".join(job2.log_lines)

    # Lỗi fatal (sai mật khẩu) → KHÔNG retry
    cm3 = _mk_cm()
    job3 = VoteJob(id="a3", email="c@outlook.com", _password="pw")
    cm3.jobs[job3.id] = job3
    cm3.order.append(job3.id)

    async def _bad_pw(job, *, proxy):
        raise VoteError("đăng nhập fail: 'mật khẩu không đúng'")

    cm3._run_job_inner = _bad_pw  # type: ignore[method-assign]
    await cm3._run_job(job3)
    assert job3.status == "error", job3.status
    assert job3.retry_count == 0, job3.retry_count


if __name__ == "__main__":
    main()
