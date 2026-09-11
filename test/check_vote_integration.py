"""Smoke: import web.server (kích hoạt mọi route + boot path) và web.vote.

Verify các route /api/vote/* được đăng ký, config dict khớp API contract
của server.py và vote.js.
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from web.vote import get_vote_manager, VoteManager, _parse_combo  # noqa: E402


def main() -> None:
    # 1. Parse combo
    email, pw = _parse_combo("taolaban007@gmail.com|Bss123@#")
    assert email == "taolaban007@gmail.com" and pw == "Bss123@#", (email, pw)

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
        "use_proxy", "candidate", "confirm_vote",
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
        "vote.confirm_vote": True,
    })
    cfg = vm.to_config_dict()
    assert cfg["engine"] == "chrome"
    assert cfg["headless"] is True
    assert cfg["use_proxy"] is False
    assert cfg["max_concurrent"] == 2
    assert cfg["job_timeout"] == 300.0
    assert cfg["candidate"] == "Anh Trai JSOL"
    assert cfg["confirm_vote"] is True

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
