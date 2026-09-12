"""Auto Vote — tự động bình chọn trên tinhhasayhi.1vote.vn.

Mỗi job = 1 combo `email|password` (tài khoản 1Zone đã đăng ký):

  1. Browser mở site → Đăng nhập → điền email/password → bấm Đăng nhập.
  2. Verify login OK (header có avatar account).
  3. Tìm candidate (mặc định "Anh Trai JSOL") → bấm "Bình chọn".
  4. Popup vote → chọn gói "1 vote".
  5. Bấm "Xem video nhận lượt bình chọn" → video dialog → bấm "Phát video".
  6. Chờ 30s countdown → nút "Bình chọn ngay" sẵn sàng.
  7. Nếu `confirm_vote=True`: bấm "Bình chọn ngay" → chờ modal "Thành công".
     Nếu False (mặc định, dry-run): dừng tại bước 6 — chỉ xác minh flow OK.

Job dùng proxy (nếu pool có): lấy public IP qua proxy (api64.ipify.org) để
ghi vào output `email|password|ip`. Vì proxy xoay IP mỗi 60s, job chạy qua
proxy phải kéo dài tối thiểu `vote.min_seconds` (mặc định 60s) — flow xong
sớm sẽ sleep phần thừa trước khi báo hoàn thành, tránh 2 account liên tiếp
dính cùng IP. Nhiều proxy + `max_concurrent` → nhiều worker song song, mỗi
job 1 proxy riêng (logic không đổi).

In-memory jobs (giống Eventista/Upi) — không persist DB, không cần mail.
Proxy: qua proxy pool config (`_resolve_job_proxy`).
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable

from .eventista import EventistaError, _launch_browser, _resolve_browser_engine

_log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────

_SITE_URL = "https://tinhhasayhi.1vote.vn"
_DEFAULT_CANDIDATE = "Anh Trai JSOL"
_MAX_LOG_LINES = 2000
# Thời gian chờ tối đa cho mỗi giai đoạn (giây).
_LOGIN_VERIFY_SECONDS = 30.0
_VIDEO_WATCH_SECONDS = 60.0
_SUCCESS_WAIT_SECONDS = 30.0
# IP echo endpoint (dual-stack, CORS mở) — dùng để lấy public IP qua proxy.
_IP_ECHO_URL = "https://api64.ipify.org?format=json"
_DEFAULT_MIN_SECONDS = 60.0  # job qua proxy tối thiểu bao lâu (proxy xoay IP mỗi 60s)


class VoteError(Exception):
    """Lỗi nghiệp vụ Auto Vote — message hiển thị thẳng trong job.error."""


class AlreadyConvertedError(VoteError):
    """Tài khoản đã được chuyển đổi sang email khác (popup 'Tài khoản đã được chuyển đổi').

    Raise trong _do_login khi phát hiện popup sorry. Manager Đổi Email bắt riêng
    để coi như success và đưa ra output luôn (yêu cầu user: đã chuyển rồi thì
    không cần chạy lại flow).
    """

    def __init__(self, message: str, converted_email: str | None = None):
        super().__init__(message)
        self.converted_email = converted_email


def _short_error(msg: str, limit: int = 160) -> str:
    """Rút gọn error cho job row: lấy dòng đầu tiên, cắt theo limit."""
    first = (msg or "").splitlines()[0] if (msg or "").splitlines() else ""
    return first[:limit]


# ── Job model ────────────────────────────────────────────────────────────


@dataclass
class VoteJob:
    id: str
    email: str
    status: str = "queued"  # queued|running|success|error|cancelled
    log_lines: list[str] = field(default_factory=list)
    error: str | None = None
    engine: str = "camoufox"
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    # Auth artifacts giữ in-memory (KHÔNG vào to_dict — tránh leak qua SSE).
    _password: str | None = field(default=None, repr=False)
    _proxy_used: str | None = field(default=None, repr=False)
    _proxy_line: str | None = field(default=None, repr=False)
    _public_ip: str | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "email": self.email,
            "status": self.status,
            "error": self.error,
            "engine": self.engine,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration": (
                (self.finished_at or time.time()) - self.started_at
                if self.started_at else None
            ),
            "log_count": len(self.log_lines),
            "proxy_used": self._proxy_used,
        }

    def to_dict_full(self) -> dict[str, Any]:
        d = self.to_dict()
        d["log_lines"] = list(self.log_lines)
        return d


# ── Combo parse ──────────────────────────────────────────────────────────


def _parse_combo(line: str) -> tuple[str, str]:
    """Parse `email|password` → (email, password). Password có thể chứa `|`."""
    line = line.strip()
    email, sep, password = line.partition("|")
    email = email.strip()
    if not sep or not email or "@" not in email:
        raise VoteError(f"combo không hợp lệ (cần email|password): {line!r}")
    return email, password.strip()


# ── Flow vote ────────────────────────────────────────────────────────────


async def _open_login_dialog(page: Any, log: Callable[[str], None]) -> None:
    """Mở dialog Đăng nhập: chờ btn-signin (2 element desktop+mobile), click
    element visible, chờ #login-form."""
    try:
        await page.wait_for_selector(
            '[data-id="btn-signin"]', state="attached", timeout=30000
        )
        clicked = await page.evaluate(
            """() => {
                const els = [...document.querySelectorAll('[data-id="btn-signin"]')];
                const el = els.find(e => e.offsetParent !== null);
                if (!el) return false;
                el.click();
                return true;
            }"""
        )
        if not clicked:
            raise VoteError("btn-signin không tồn tại trên trang")
        await page.wait_for_selector("#login-form", state="visible", timeout=10000)
    except VoteError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise VoteError(f"không mở được dialog Đăng nhập: {exc}") from exc
    log("● Mở dialog Đăng nhập")


async def _do_login(
    page: Any,
    *,
    email: str,
    password: str,
    log: Callable[[str], None],
) -> None:
    """Điền email/password trong #login-form → bấm Đăng nhập → chờ dialog đóng."""
    await page.locator('#login-form input[name="email"]').press_sequentially(
        email, delay=random.randint(30, 70)
    )
    await page.locator('#login-form input[name="password"]').press_sequentially(
        password, delay=random.randint(30, 70)
    )
    log("● Bấm Đăng nhập")
    try:
        await page.locator('[data-id="btn-login"]').click(timeout=15000)
    except Exception as exc:  # noqa: BLE001
        raise VoteError(f"không bấm được nút Đăng nhập: {exc}") from exc

    deadline = time.monotonic() + _LOGIN_VERIFY_SECONDS
    last_body = ""
    while time.monotonic() < deadline:
        await asyncio.sleep(1.5)
        try:
            dialog_visible = await page.locator("#login-form").is_visible()
            last_body = await page.evaluate(
                "() => (document.body ? document.body.innerText : '') || ''"
            )
        except Exception:  # noqa: BLE001
            continue
        if not dialog_visible:
            log("✓ Đăng nhập thành công")
            return
        low = last_body.lower()
        # ── Popup "Tài khoản đã được chuyển đổi" — chạy trước đó đã đổi sang mail mới.
        # User yêu cầu: phát hiện popup này thì coi như success và đưa output luôn.
        if "đã được chuyển đổi" in low or "da duoc chuyen doi" in low:
            m = re.search(
                r"chuyển đổi sang\s+([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})",
                last_body,
                re.IGNORECASE,
            )
            converted = m.group(1).strip().rstrip(".,;") if m else None
            # Đóng popup "Đã hiểu" để browser không kẹt
            try:
                await page.evaluate(
                    """() => {
                        const btns = [...document.querySelectorAll('button')];
                        const b = btns.find(x => (x.innerText||'').includes('Đã hiểu'));
                        if (b) b.click();
                    }"""
                )
            except Exception:
                pass
            log(f"⚠ Tài khoản đã được chuyển đổi sang {converted or 'unknown'} — coi như success")
            raise AlreadyConvertedError(
                f"Tài khoản đã được chuyển đổi sang {converted or 'unknown'}",
                converted_email=converted,
            )
        for hint in (
            "mật khẩu không đúng",
            "sai mật khẩu",
            "không tồn tại",
            "không chính xác",
            "email hoặc mật khẩu",
            "thất bại",
        ):
            if hint in low:
                raise VoteError(
                    f"đăng nhập fail: {hint!r} — {last_body[:300]}"
                )
    raise VoteError(
        f"không xác nhận được đăng nhập sau {int(_LOGIN_VERIFY_SECONDS)}s — {last_body[:300]}"
    )


async def _click_candidate_vote(
    page: Any,
    *,
    candidate: str,
    log: Callable[[str], None],
) -> None:
    """Tìm candidate card → bấm nút "Bình chọn" trong card đó.

    Card là `.candidate-card-dark` chứa `<img alt="<candidate>">`. Nếu không
    tìm thấy theo alt, fallback bấm button "Bình chọn" visible đầu tiên.
    """
    clicked = await page.evaluate(
        """(candidate) => {
            const imgs = [...document.querySelectorAll(`img[alt="${candidate}"]`)];
            for (const img of imgs) {
                let card = img.closest('.candidate-card-dark');
                if (!card) continue;
                const btn = [...card.querySelectorAll('button')].find(
                    b => b.innerText.includes('Bình chọn')
                );
                if (btn && btn.offsetParent !== null) {
                    btn.click();
                    return true;
                }
            }
            return false;
        }""",
        candidate,
    )
    if not clicked:
        # Fallback: bấm nút "Bình chọn" visible đầu tiên trên trang.
        clicked = await page.evaluate(
            """() => {
                const btn = [...document.querySelectorAll('button')].find(
                    b => b.innerText.includes('Bình chọn') && b.offsetParent !== null
                );
                if (!btn) return false;
                btn.click();
                return true;
            }"""
        )
        if not clicked:
            raise VoteError("không tìm thấy nút Bình chọn trên trang")
        log("● Bấm Bình chọn (fallback — không khớp candidate card)")
    else:
        log(f"● Bấm Bình chọn — {candidate}")


async def _click_vote_package(page: Any, log: Callable[[str], None]) -> None:
    """Trong popup vote, chọn gói "1 vote" (button chứa text bắt đầu "1 vote").

    Popup mở có animation — poll retry tới deadline thay vì evaluate 1 lần.
    """
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        clicked = await page.evaluate(
            """() => {
                const btn = [...document.querySelectorAll('button')].find(
                    b => b.innerText.trim().startsWith('1 vote')
                      && b.offsetParent !== null
                );
                if (!btn) return false;
                btn.click();
                return true;
            }"""
        )
        if clicked:
            log("● Chọn gói 1 vote")
            return
        await asyncio.sleep(1.0)
    raise VoteError("không tìm thấy gói '1 vote' trong popup")


async def _open_video(page: Any, log: Callable[[str], None]) -> None:
    """Bấm "Xem video nhận lượt bình chọn" → chờ video dialog → bấm "Phát video"."""
    deadline = time.monotonic() + 15.0
    clicked = False
    while time.monotonic() < deadline:
        clicked = await page.evaluate(
            """() => {
                const btn = [...document.querySelectorAll('button')].find(
                    b => b.innerText.includes('Xem video nhận lượt bình chọn')
                      && b.offsetParent !== null
                );
                if (!btn) return false;
                btn.click();
                return true;
            }"""
        )
        if clicked:
            break
        await asyncio.sleep(1.0)
    if not clicked:
        raise VoteError("không tìm thấy nút 'Xem video nhận lượt bình chọn'")
    log("● Bấm Xem video nhận lượt bình chọn")

    try:
        await page.wait_for_selector(
            'button[aria-label="Phát video"]', state="visible", timeout=15000
        )
    except Exception as exc:  # noqa: BLE001
        raise VoteError(f"video dialog không mở: {exc}") from exc
    try:
        await page.locator('button[aria-label="Phát video"]').click(timeout=10000)
    except Exception as exc:  # noqa: BLE001
        raise VoteError(f"không bấm được Phát video: {exc}") from exc
    log("● Phát video — chờ 30s countdown...")

    # YouTube embed autoplay=0 → cần click chuột thật vào player để phát.
    # Nếu click fail, `_wait_video_done` sẽ retry click mỗi 10s.
    if await _click_youtube_player(page):
        log("● Click vào player — video bắt đầu phát")


async def _click_youtube_player(page: Any) -> bool:
    """Click chuột thật vào tâm YouTube player (autoplay=0 cần click để phát)."""
    try:
        iframe = page.locator("iframe[src*='youtube.com/embed']").first
        if await iframe.count() == 0:
            return False
        box = await iframe.bounding_box()
        if not box or box["width"] <= 0 or box["height"] <= 0:
            return False
        await page.mouse.click(
            box["x"] + box["width"] / 2,
            box["y"] + box["height"] / 2,
        )
        return True
    except Exception:  # noqa: BLE001
        return False


async def _read_video_countdown(page: Any) -> int | None:
    """Đọc số countdown (giây) trên video dialog — trả None nếu không thấy."""
    try:
        return await page.evaluate(
            """() => {
                const els = [...document.querySelectorAll('[class*=tabular-nums]')]
                    .filter(e => e.offsetParent !== null);
                for (const el of els) {
                    const t = (el.innerText || '').trim();
                    if (/^\\d{1,3}$/.test(t)) return parseInt(t, 10);
                }
                return null;
            }"""
        )
    except Exception:  # noqa: BLE001
        return None


async def _wait_video_done(page: Any, log: Callable[[str], None]) -> None:
    """Chờ video 30s xong (nút "Bình chọn ngay" sẵn sàng).

    Video chỉ play sau khi click thật vào player. Nếu sau 10s nút chưa xuất
    hiện → click lại player (countdown kẹt do pause/autoplay chặn).
    """
    deadline = time.monotonic() + _VIDEO_WATCH_SECONDS
    last_click = time.monotonic()
    while time.monotonic() < deadline:
        try:
            btn = page.locator('button:has-text("Bình chọn ngay")').first
            if await btn.is_visible() and await btn.is_enabled():
                log("✓ Video đã xem xong — nút Bình chọn ngay sẵn sàng")
                return
        except Exception:  # noqa: BLE001
            pass
        if time.monotonic() - last_click >= 10.0:
            count = await _read_video_countdown(page)
            if await _click_youtube_player(page):
                log(f"● Click lại player (video chưa xong — countdown {count})")
            last_click = time.monotonic()
        await asyncio.sleep(2.0)
    raise VoteError(
        f"video không hoàn thành trong {int(_VIDEO_WATCH_SECONDS)}s "
        "(nút Bình chọn ngay không sẵn sàng)"
    )


async def _confirm_vote(page: Any, log: Callable[[str], None]) -> None:
    """Bấm "Bình chọn ngay" → chờ modal "Thành công"."""
    try:
        await page.locator('button:has-text("Bình chọn ngay")').first.click(timeout=10000)
    except Exception as exc:  # noqa: BLE001
        raise VoteError(f"không bấm được Bình chọn ngay: {exc}") from exc
    log("● Bấm Bình chọn ngay — chờ xác nhận...")

    deadline = time.monotonic() + _SUCCESS_WAIT_SECONDS
    while time.monotonic() < deadline:
        await asyncio.sleep(1.5)
        try:
            ok = await page.evaluate(
                """() => {
                    const el = [...document.querySelectorAll('h3')].find(
                        h => h.innerText.includes('Thành công')
                    );
                    return !!(el && el.offsetParent !== null);
                }"""
            )
        except Exception:  # noqa: BLE001
            ok = False
        if ok:
            log("✓ Bình chọn thành công")
            return
    raise VoteError("không thấy modal Thành công sau khi bấm Bình chọn ngay")


async def _fetch_public_ip(page: Any) -> str | None:
    """Lấy public IP mà browser đang đi qua (proxy hay direct).

    Fetch trong page hiện tại → request đi qua proxy context của browser,
    không cần httpx riêng. Endpoint ipify có CORS mở. Fail → None (job
    không fail vì không lấy được IP).
    """
    try:
        ip = await page.evaluate(
            """(url) => fetch(url, {signal: AbortSignal.timeout(10000)})
                .then(r => r.json())
                .then(d => (d && d.ip) ? String(d.ip) : null)
                .catch(() => null)""",
            _IP_ECHO_URL,
        )
        return str(ip) if ip else None
    except Exception:  # noqa: BLE001
        return None


async def _do_vote(
    page: Any,
    *,
    email: str,
    password: str,
    candidate: str,
    confirm_vote: bool,
    log: Callable[[str], None],
) -> str | None:
    """Thực hiện flow bình chọn trên trang. Raise VoteError nếu fail.

    Trả về public IP đang dùng (None nếu không lấy được).
    """
    log(f"● Mở trang đích {_SITE_URL}")
    await page.goto(_SITE_URL, wait_until="domcontentloaded", timeout=60000)

    public_ip = await _fetch_public_ip(page)
    if public_ip:
        log(f"● Public IP: {public_ip}")
    else:
        log("● Không lấy được public IP (ipify fail)")

    await _open_login_dialog(page, log)
    await _do_login(page, email=email, password=password, log=log)
    await _click_candidate_vote(page, candidate=candidate, log=log)
    await _click_vote_package(page, log)
    await _open_video(page, log)
    await _wait_video_done(page, log)

    if confirm_vote:
        await _confirm_vote(page, log)
    else:
        log("● Dry-run: dừng trước bước bấm Bình chọn ngay (chưa vote thật)")
    return public_ip


# ── Manager ──────────────────────────────────────────────────────────────


class VoteManager:
    """Quản lý Auto Vote jobs: queue + workers + SSE (in-memory).

    Config hydrate từ Settings Store qua ``apply_settings`` (startup boot).
    """

    def __init__(self, *, max_concurrent: int = 1) -> None:
        self._max = max(1, min(30, int(max_concurrent)))
        self._job_timeout: float = 600.0
        self._engine: str = "camoufox"
        self._headless: bool = False
        self._use_proxy: bool = True
        self._candidate: str = _DEFAULT_CANDIDATE
        self._confirm_vote: bool = False
        self._min_seconds: float = _DEFAULT_MIN_SECONDS

        self.jobs: dict[str, VoteJob] = {}
        self.order: list[str] = []
        self._job_queue: asyncio.Queue[str] = asyncio.Queue()
        self._tasks: dict[str, asyncio.Task] = {}
        self._workers: list[asyncio.Task] = []
        self._worker_started = False

    # ── Config accessors ──────────────────────────────────────────────

    @property
    def max_concurrent(self) -> int:
        return self._max

    @property
    def job_timeout(self) -> float:
        return self._job_timeout

    @property
    def engine(self) -> str:
        return self._engine

    @property
    def headless(self) -> bool:
        return self._headless

    @property
    def use_proxy(self) -> bool:
        return self._use_proxy

    @property
    def candidate(self) -> str:
        return self._candidate

    @property
    def confirm_vote(self) -> bool:
        return self._confirm_vote

    @property
    def min_seconds(self) -> float:
        return self._min_seconds

    def set_engine(self, value: str) -> None:
        if value not in ("camoufox", "playwright", "chrome", "cloakbrowser"):
            raise ValueError(
                f"engine phải là camoufox|playwright|chrome|cloakbrowser, nhận {value!r}"
            )
        self._engine = value

    def set_max_concurrent(self, value: int) -> None:
        if not (1 <= value <= 30):
            raise ValueError(f"max_concurrent phải trong [1, 30], nhận {value}")
        self._max = int(value)
        self._ensure_workers()

    def set_headless(self, value: bool) -> None:
        self._headless = bool(value)

    def set_use_proxy(self, value: bool) -> None:
        self._use_proxy = bool(value)

    def set_candidate(self, value: str) -> None:
        value = (value or "").strip()
        if not value:
            raise ValueError("candidate không được rỗng")
        self._candidate = value

    def set_confirm_vote(self, value: bool) -> None:
        self._confirm_vote = bool(value)

    def set_min_seconds(self, value: float) -> None:
        if not (0 <= value <= 300):
            raise ValueError(f"min_seconds phải trong [0, 300], nhận {value}")
        self._min_seconds = float(value)

    def set_job_timeout(self, value: float) -> None:
        if not (30 <= value <= 3600):
            raise ValueError(f"job_timeout phải trong [30, 3600], nhận {value}")
        self._job_timeout = float(value)

    def apply_settings(self, settings: dict) -> None:
        """Hydrate fields từ settings dict (startup boot). Best-effort."""
        if "vote.max_concurrent" in settings:
            val = int(settings["vote.max_concurrent"])
            if 1 <= val <= 30:
                self._max = val
        if "vote.job_timeout" in settings:
            val = float(settings["vote.job_timeout"])
            if 30 <= val <= 3600:
                self._job_timeout = val
        if "vote.engine" in settings and settings["vote.engine"] in (
            "camoufox", "playwright", "chrome", "cloakbrowser"
        ):
            self._engine = settings["vote.engine"]
        if "vote.headless" in settings:
            self._headless = bool(settings["vote.headless"])
        if "vote.use_proxy" in settings:
            self._use_proxy = bool(settings["vote.use_proxy"])
        if "vote.candidate" in settings:
            value = (settings["vote.candidate"] or "").strip()
            if value:
                self._candidate = value
        if "vote.confirm_vote" in settings:
            self._confirm_vote = bool(settings["vote.confirm_vote"])
        if "vote.min_seconds" in settings:
            val = float(settings["vote.min_seconds"])
            if 0 <= val <= 300:
                self._min_seconds = val

    def to_config_dict(self) -> dict[str, Any]:
        return {
            "max_concurrent": self._max,
            "job_timeout": self._job_timeout,
            "engine": self._engine,
            "headless": self._headless,
            "use_proxy": self._use_proxy,
            "candidate": self._candidate,
            "confirm_vote": self._confirm_vote,
            "min_seconds": self._min_seconds,
        }

    # ── SSE broadcast ──────────────────────────────────────────────────

    def _broadcast(self, event: dict[str, Any]) -> None:
        from .manager import _sse_mux

        if _sse_mux is not None:
            _sse_mux.publish("vote", event)

    def _broadcast_job(self, job: VoteJob) -> None:
        self._broadcast({"type": "job", "job": job.to_dict()})

    def _job_log(self, job: VoteJob, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        job.log_lines.append(line)
        if len(job.log_lines) > _MAX_LOG_LINES:
            job.log_lines = job.log_lines[-_MAX_LOG_LINES:]
        self._broadcast({"type": "log", "job_id": job.id, "line": line})

    # ── Workers ─────────────────────────────────────────────────────────

    def _ensure_workers(self) -> None:
        if not self._worker_started:
            self._worker_started = True
        self._workers = [t for t in self._workers if not t.done()]
        while len(self._workers) < self._max:
            task = asyncio.create_task(self._worker_loop())
            self._workers.append(task)
        while len(self._workers) > self._max:
            task = self._workers.pop()
            task.cancel()

    async def _worker_loop(self) -> None:
        try:
            while True:
                job_id = await self._job_queue.get()
                job = self.jobs.get(job_id)
                if job is None or job.status != "queued":
                    continue
                inner = asyncio.create_task(self._run_job(job))
                self._tasks[job_id] = inner
                try:
                    await inner
                except asyncio.CancelledError:
                    current = asyncio.current_task()
                    if current is not None and current.cancelled():
                        raise
                    if inner.cancelled():
                        continue
                    raise
                finally:
                    self._tasks.pop(job_id, None)
        except asyncio.CancelledError:
            pass

    # ── Public CRUD ────────────────────────────────────────────────────

    def add_jobs(self, combos: list[str]) -> list[VoteJob]:
        existing = {j.email.lower() for j in self.jobs.values() if j.status != "cancelled"}
        out: list[VoteJob] = []
        for raw in combos:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            try:
                email, password = _parse_combo(line)
            except VoteError as exc:
                jid = uuid.uuid4().hex[:12]
                job = VoteJob(
                    id=jid, email="<invalid>",
                    status="error", error=str(exc), finished_at=time.time(),
                )
                self.jobs[jid] = job
                self.order.append(jid)
                self._broadcast_job(job)
                out.append(job)
                continue
            if email.lower() in existing:
                jid = uuid.uuid4().hex[:12]
                job = VoteJob(
                    id=jid, email=email,
                    status="error",
                    error="combo đã có trong danh sách (chưa kết thúc)",
                    finished_at=time.time(),
                )
                self.jobs[jid] = job
                self.order.append(jid)
                self._broadcast_job(job)
                out.append(job)
                continue
            existing.add(email.lower())
            jid = uuid.uuid4().hex[:12]
            job = VoteJob(
                id=jid,
                email=email,
                engine=self._engine,
                _password=password,
            )
            self.jobs[jid] = job
            self.order.append(jid)
            self._job_queue.put_nowait(jid)
            self._broadcast_job(job)
            out.append(job)
        self._ensure_workers()
        return out

    async def stop_all(self) -> int:
        stopped = 0
        for job in self.jobs.values():
            if job.status == "queued":
                job.status = "cancelled"
                job.finished_at = time.time()
                self._broadcast_job(job)
                stopped += 1
        for task in list(self._tasks.values()):
            task.cancel()
        for task in self._workers:
            task.cancel()
        self._worker_started = False
        return stopped

    async def retry_failed(self) -> int:
        retried = 0
        for job in self.jobs.values():
            if job.status in ("error", "cancelled"):
                job.status = "queued"
                job.error = None
                job.finished_at = None
                job.started_at = None
                self._job_queue.put_nowait(job.id)
                self._broadcast_job(job)
                retried += 1
        if retried:
            self._ensure_workers()
        return retried

    def retry_job(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if job is None or job.status not in ("error", "cancelled"):
            return False
        job.status = "queued"
        job.error = None
        job.finished_at = None
        job.started_at = None
        self._job_queue.put_nowait(job.id)
        self._broadcast_job(job)
        self._ensure_workers()
        return True

    def clear_finished(self) -> int:
        removed = 0
        for jid in list(self.jobs.keys()):
            job = self.jobs[jid]
            if job.status in ("success", "error", "cancelled"):
                del self.jobs[jid]
                if jid in self.order:
                    self.order.remove(jid)
                removed += 1
        return removed

    def clear_all(self) -> int:
        removed = 0
        for jid in list(self.jobs.keys()):
            job = self.jobs[jid]
            if job.status == "running":
                task = self._tasks.get(jid)
                if task:
                    task.cancel()
            del self.jobs[jid]
            if jid in self.order:
                self.order.remove(jid)
            removed += 1
        return removed

    def list_outputs(self) -> dict[str, list[str]]:
        success: list[str] = []
        errors: list[str] = []
        for jid in self.order:
            job = self.jobs.get(jid)
            if not job:
                continue
            if job.status == "success":
                success.append(
                    f"{job.email}|{job._password or ''}|{job._public_ip or ''}"
                )
            elif job.status == "error":
                errors.append(f"{job.email}  →  {job.error or 'unknown'}")
        return {"success": success, "errors": errors}

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        job = self.jobs.get(job_id)
        return job.to_dict_full() if job else None

    def remove_job(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if job is None:
            return False
        if job.status == "running":
            task = self._tasks.get(job_id)
            if task:
                task.cancel()
        del self.jobs[job_id]
        if job_id in self.order:
            self.order.remove(job_id)
        return True

    def list_jobs(self) -> list[dict[str, Any]]:
        out = []
        for jid in self.order:
            job = self.jobs.get(jid)
            if job:
                out.append(job.to_dict())
        return out

    # ── Job runner ─────────────────────────────────────────────────────

    async def _run_job(self, job: VoteJob) -> None:
        job.status = "running"
        job.started_at = time.time()
        start_mono = time.monotonic()
        self._broadcast_job(job)
        self._job_log(job, "● Bắt đầu job")

        proxy: str | None = None
        if self._use_proxy:
            try:
                from .manager import _resolve_job_proxy

                proxy, _line = await _resolve_job_proxy(log=lambda m: self._job_log(job, m))
                job._proxy_used = proxy
                job._proxy_line = _line
                if proxy:
                    self._job_log(job, f"● Dùng proxy {proxy[:40]}...")
                else:
                    self._job_log(job, "● Proxy pool rỗng — chạy direct")
            except Exception as exc:  # noqa: BLE001
                self._job_log(job, f"proxy resolve fail — chạy direct: {exc}")

        try:
            await asyncio.wait_for(
                self._run_job_inner(job, proxy=proxy),
                timeout=self._job_timeout,
            )
        except asyncio.TimeoutError:
            job.error = f"job timeout sau {int(self._job_timeout)}s"
            job.status = "error"
            self._job_log(job, f"✗ {job.error}")
        except VoteError as exc:
            job.error = _short_error(str(exc))
            job.status = "error"
            self._job_log(job, f"✗ {job.error}")
        except EventistaError as exc:
            job.error = _short_error(str(exc))
            job.status = "error"
            self._job_log(job, f"✗ {job.error}")
        except Exception as exc:  # noqa: BLE001
            await self._handle_browser_failure(job, exc)
            job.error = _short_error(f"{type(exc).__name__}: {exc}")
            job.status = "error"
            self._job_log(job, f"✗ {job.error}")
        else:
            # Proxy xoay IP mỗi 60s → job qua proxy phải kéo dài tối thiểu
            # min_seconds để account kế tiếp không dính cùng IP. Chỉ gate khi
            # có proxy thật (direct không cần xoay). Sleep nằm ngoài wait_for
            # timeout; bị hủy tự nhiên khi Stop All cancel task.
            if proxy and self._min_seconds > 0:
                elapsed = time.monotonic() - start_mono
                wait = self._min_seconds - elapsed
                if wait > 0:
                    self._job_log(
                        job,
                        f"● Flow xong sau {elapsed:.0f}s — chờ thêm {wait:.0f}s "
                        f"cho đủ {int(self._min_seconds)}s (proxy xoay IP mỗi 60s)",
                    )
                    await asyncio.sleep(wait)
            job.status = "success"
            self._job_log(job, "✓ Vote flow hoàn thành")
        finally:
            job.finished_at = time.time()
            self._broadcast_job(job)

    async def _handle_browser_failure(self, job: VoteJob, exc: Exception) -> None:
        """Lỗi browser/network → mark proxy chết (reuse cơ chế Eventista/Reg)."""
        from _browser_retry import is_network_error
        from .proxy_pool import get_proxy_pool

        if not job._proxy_line:
            return
        if not is_network_error(exc):
            return
        try:
            if get_proxy_pool().mark_dead(job._proxy_line):
                from .manager import _mask_proxy

                self._job_log(
                    job,
                    f"[proxy] {_mask_proxy(job._proxy_line)} lỗi network — loại khỏi pool",
                )
        except Exception as e:  # noqa: BLE001
            self._job_log(job, f"[proxy] mark_dead fail: {e}")

    async def _run_job_inner(self, job: VoteJob, *, proxy: str | None) -> None:
        if not job._password:
            raise VoteError("combo thiếu password — không vote được")
        engine = _resolve_browser_engine(
            self._engine,
            log=lambda m: self._job_log(job, m),
        )
        job.engine = engine

        page, _handle, close = await _launch_browser(
            engine, headless=self._headless, proxy=proxy
        )
        try:
            job._public_ip = await _do_vote(
                page,
                email=job.email,
                password=job._password,
                candidate=self._candidate,
                confirm_vote=self._confirm_vote,
                log=lambda m: self._job_log(job, m),
            )
        finally:
            try:
                await close()
            except Exception as exc:  # noqa: BLE001
                self._job_log(job, f"close browser: {exc}")


_vote_manager: VoteManager | None = None


def get_vote_manager() -> VoteManager:
    global _vote_manager  # noqa: PLW0603
    if _vote_manager is None:
        _vote_manager = VoteManager(max_concurrent=1)
    return _vote_manager
