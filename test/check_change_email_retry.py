import pathlib, ast, sys
sys.path.insert(0, ".")
# syntax
for p in ["web/change_email.py", "web/vote.py", "mail_providers.py"]:
    try:
        ast.parse(pathlib.Path(p).read_text(encoding="utf-8"))
        print(f"OK syntax {p}")
    except Exception as e:
        print(f"FAIL {p}: {e}")
        sys.exit(1)

from web.change_email import ChangeEmailManager, ChangeEmailJob

# test auto_retry fields
m = ChangeEmailManager()
assert hasattr(m, "_auto_retry"), "missing _auto_retry"
assert m._auto_retry == True, "default should be True"
assert m._auto_retry_max == 3
print("OK auto_retry defaults")

# test _is_fatal
assert m._is_fatal("Email đã được sử dụng") == True
assert m._is_fatal("Turnstile không solve trong 120s") == False
assert m._is_fatal("InvalidProxy: Failed to connect to proxy") == False
assert m._is_fatal("không thấy popup 'Chờ xác nhận'") == False
print("OK _is_fatal")

# test retry scheduling
import asyncio

async def test_retry():
    job = ChangeEmailJob(id="test123", old_email="a@old.com", new_email="b@new.com", _old_password="p", _new_password="p2", _refresh_token="M.C123", _client_id="11111111-2222-3333-4444-555555555555")
    job.status = "error"
    job.error = "Turnstile không solve trong 120s"
    job.retry_count = 0
    m.jobs[job.id] = job
    m.order.append(job.id)
    ok = await m._maybe_auto_retry(job)
    assert ok == True, "should retry turnstile"
    assert job.status == "queued"
    assert job.retry_count == 1
    print("OK retry transient")

    # fatal should not retry
    job2 = ChangeEmailJob(id="test456", old_email="c@old.com", new_email="d@new.com", _old_password="p", _new_password="p2", _refresh_token="M.C123", _client_id="22222222-3333-4444-5555-666666666666")
    job2.status = "error"
    job2.error = "yêu cầu đổi email bị chặn: 'đã được sử dụng'"
    job2.retry_count = 0
    m.jobs[job2.id] = job2
    m.order.append(job2.id)
    ok2 = await m._maybe_auto_retry(job2)
    assert ok2 == False, "fatal should not retry"
    assert job2.status == "error"
    print("OK no retry fatal")

    # max retries
    job3 = ChangeEmailJob(id="test789", old_email="e@old.com", new_email="f@new.com", _old_password="p", _new_password="p2", _refresh_token="M.C123", _client_id="33333333-4444-5555-6666-777777777777")
    job3.status = "error"
    job3.error = "proxy fail"
    job3.retry_count = 3
    m.jobs[job3.id] = job3
    m.order.append(job3.id)
    ok3 = await m._maybe_auto_retry(job3)
    assert ok3 == False, "max retries should block"
    print("OK max retries")

asyncio.run(test_retry())

# check proxy path
from _browser_retry import is_network_error
assert is_network_error(Exception("InvalidProxy: Failed to connect to proxy: http://corywhite49939:mzy5mtmzmtu3nq==@180.93.2.171:3129")) == True
assert is_network_error(Exception("Turnstile không solve trong 120s")) == False
print("OK is_network_error")

print("all checks passed")
