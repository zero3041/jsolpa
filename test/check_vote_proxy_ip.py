"""Check Auto Vote: proxy IP output + min-duration (proxy xoay IP mỗi 60s).

Verify:
  1. Config `vote.min_seconds` (setter, apply_settings, to_config_dict).
  2. `_fetch_public_ip` lấy IP qua page (proxy context) — success + fail.
  3. `_run_job` với proxy: flow xong sớm → kéo dài đủ min_seconds.
  4. Output success format `email|password|ip`.
"""
from __future__ import annotations

import asyncio
import sys
import time

sys.path.insert(0, ".")

from web.vote import VoteManager, VoteJob, _fetch_public_ip  # noqa: E402


class _FakePage:
    """Mock page.evaluate — trả IP nếu `ip` set, raise nếu `fail`."""

    def __init__(self, ip: str | None = "9.8.7.6", fail: bool = False):
        self.ip = ip
        self.fail = fail

    async def evaluate(self, script: str, *args):
        if self.fail:
            raise RuntimeError("evaluate fail")
        return self.ip


def check_config() -> None:
    vm = VoteManager()
    assert vm.min_seconds == 60.0, vm.min_seconds

    vm.apply_settings({"vote.min_seconds": 120})
    assert vm.min_seconds == 120.0, vm.min_seconds

    vm.apply_settings({"vote.min_seconds": 9999})  # out of range → giữ nguyên
    assert vm.min_seconds == 120.0, vm.min_seconds

    vm.set_min_seconds(0)
    assert vm.min_seconds == 0.0, vm.min_seconds

    try:
        vm.set_min_seconds(301)
        raise AssertionError("set_min_seconds(301) phải raise")
    except ValueError:
        pass

    cfg = vm.to_config_dict()
    assert cfg["min_seconds"] == 0.0, cfg
    print("PASS: config min_seconds")


def check_fetch_ip() -> None:
    ip = asyncio.run(_fetch_public_ip(_FakePage(ip="1.2.3.4")))
    assert ip == "1.2.3.4", ip

    ip = asyncio.run(_fetch_public_ip(_FakePage(ip=None)))
    assert ip is None, ip

    ip = asyncio.run(_fetch_public_ip(_FakePage(fail=True)))
    assert ip is None, ip  # fail không raise
    print("PASS: _fetch_public_ip (success/fail)")


def check_min_duration_and_output() -> None:
    import web.manager as manager
    import web.vote as vote_mod

    async def fake_resolve(log=None, **kw):
        return ("http://u:p@1.2.3.4:8080", "1.2.3.4:8080")

    async def fake_inner(self, job, *, proxy):
        job._public_ip = "8.8.4.4"

    manager._resolve_job_proxy = fake_resolve
    vote_mod.VoteManager._run_job_inner = fake_inner

    vm = VoteManager(max_concurrent=1)
    vm._min_seconds = 1.0  # test nhanh — gate giống 60s
    job = VoteJob(id="t1", email="acc1@gmail.com", _password="pw1")
    vm.jobs[job.id] = job
    vm.order.append(job.id)

    t0 = time.monotonic()
    asyncio.run(vm._run_job(job))
    elapsed = time.monotonic() - t0

    assert job.status == "success", job.status
    assert elapsed >= 1.0, f"job phải kéo dài >= min_seconds, elapsed={elapsed:.2f}"
    assert job._public_ip == "8.8.4.4", job._public_ip

    out = vm.list_outputs()
    assert out["success"] == ["acc1@gmail.com|pw1|8.8.4.4"], out["success"]
    print(f"PASS: min-duration ({elapsed:.2f}s >= 1.0s) + output tk|mk|ip")


def check_direct_no_wait() -> None:
    """Không proxy → không gate min-duration."""
    import web.manager as manager
    import web.vote as vote_mod

    async def fake_resolve(log=None, **kw):
        return (None, None)  # pool rỗng → direct

    async def fake_inner(self, job, *, proxy):
        job._public_ip = "9.9.9.9"

    manager._resolve_job_proxy = fake_resolve
    vote_mod.VoteManager._run_job_inner = fake_inner

    vm = VoteManager(max_concurrent=1)
    vm._min_seconds = 60.0
    job = VoteJob(id="t2", email="acc2@gmail.com", _password="pw2")
    vm.jobs[job.id] = job
    vm.order.append(job.id)

    t0 = time.monotonic()
    asyncio.run(vm._run_job(job))
    elapsed = time.monotonic() - t0

    assert job.status == "success", job.status
    assert elapsed < 5.0, f"direct không được chờ min, elapsed={elapsed:.2f}"
    out = vm.list_outputs()
    assert out["success"] == ["acc2@gmail.com|pw2|9.9.9.9"], out["success"]
    print(f"PASS: direct không gate ({elapsed:.2f}s) + output tk|mk|ip")


def main() -> None:
    check_config()
    check_fetch_ip()
    check_min_duration_and_output()
    check_direct_no_wait()
    print("ALL PASS")


if __name__ == "__main__":
    main()