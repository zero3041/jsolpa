"""Smoke: import web.server (kích hoạt mọi route + boot path) và web.vote.

Verify các route /api/vote/* được đăng ký, config dict khớp API contract
của server.py và vote.js.
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from web.vote import (  # noqa: E402
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
        "/api/vote/jobs/{job_id}",
        "/api/vote/jobs/{job_id}/retry",
        "/api/vote/config",
    ):
        assert expected in paths, f"route thiếu: {expected}"

    print("PASS: web.vote + web.server routes OK")
    print(f"  config: {cfg}")


if __name__ == "__main__":
    main()
