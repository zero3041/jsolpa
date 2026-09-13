"""Đổi Email 1Zone — chuyển tài khoản 1vote sang địa chỉ email mới.

UI có 2 khung nhập (KHÔNG ghép cứng cặp mới/cũ):

  - Khung "Tài khoản 1Zone" (mailcu): mỗi dòng ``email|password`` hoặc
    ``email<TAB>password`` — account đang dùng trên site, sẽ bị chuyển email.
  - Khung "Mailbox mới" (hotmail): mỗi dòng ``email|pwd|refresh_token|client_id``
    — hộp thư sẽ nhận mail kích hoạt + thành email mới của tài khoản.

Manager ghép cặp tuần tự (account[i] + mailbox[i]), bỏ qua:
  - account đã được dùng thành công (persist qua settings key
    ``change_email.used_accounts``) — tránh đổi lại gây lỗi;
  - mailbox đã được dùng (``change_email.used_mailboxes``) — tránh 2 account
    cùng đổi sang 1 email;
  - account/mailbox đang có job queued/running.

Flow (theo record `changemail/`):

  1. Mở site → Đăng nhập bằng account 1Zone.
  2. Click tab hạng mục (mặc định "THE GROUP PERFORMANCE ICON").
  3. Bấm "Bình chọn" trên candidate card (mặc định "Xoay Vòng").
  4. Trong popup vote → chọn gói "1 vote" (Vote tặng).
  5. Bấm "Chuyển đổi ngay" → dialog "Chuyển đổi email".
  6. Điền email mới → giải Turnstile (mode dùng chung flow Reg Eventista)
     → bấm "Tiếp tục" → chờ popup "Chờ xác nhận".
  7. Poll hộp thư MỚI qua Graph API → trích link
     ``https://account.faniesta.com/v2/user/email-change/verify?token=...``.
  8. Mở link trong CHÍNH phiên browser đang chạy → chờ "Chuyển đổi thành công".

Output success: ``mailcu|mailmoi|pass``.

In-memory jobs (giống Eventista/Vote) — không persist DB.
Proxy: qua proxy pool config (`_resolve_job_proxy`).
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import httpx

from mail_providers import OutlookCombo, OutlookComboError
from .eventista import (
    EventistaError,
    _ACTIVATION_SUBJECTS,
    _launch_browser,
    _resolve_browser_engine,
    _short_error,
    _solve_turnstile,
)
from .mail_reader import _refresh_access
from .vote import AlreadyConvertedError, VoteError, _do_login, _open_login_dialog

_log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────

_SITE_URL = "https://tinhhasayhi.1vote.vn"
_DEFAULT_CANDIDATE = "Xoay Vòng"
_DEFAULT_CATEGORY = "THE GROUP PERFORMANCE ICON"
_TURNSTILE_CONTAINER = ".eventista-custom-turnstile"
_CHANGE_EMAIL_URL_RE = re.compile(
    r"https://account\.faniesta\.com/v2/user/email-change/verify\?token=[^\"'\s<>]+"
)
_MAX_LOG_LINES = 2000
_CLICK_WAIT_SECONDS = 20.0
_POLL_INTERVAL_SECONDS = 12.0
_SUBMIT_WAIT_SECONDS = 60.0
_OPEN_LINK_WAIT_SECONDS = 60.0
# Mail nhận trước mốc này (giây) bị bỏ qua — tránh nhặt link cũ trong hộp thư.
_SINCE_MARGIN_SECONDS = 90

# Helper JS: visible thật (loại display:none, visibility:hidden, opacity:0,
# ancestor height/width = 0 — panel ẩn dạng grid-rows-[0fr] của site).
_VISIBLE_FN = """
function __ceVisible(el) {
  if (!el) return false;
  let node = el;
  while (node && node !== document.body) {
    const r = node.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return false;
    const st = getComputedStyle(node);
    if (st.display === 'none' || st.visibility === 'hidden' || st.opacity === '0') return false;
    node = node.parentElement;
  }
  return true;
}
"""


class ChangeEmailError(Exception):
    """Lỗi nghiệp vụ Đổi Email — message hiển thị thẳng trong job.error."""


# ── Job model ────────────────────────────────────────────────────────────


@dataclass
class ChangeEmailJob:
    id: str
    old_email: str
    new_email: str
    status: str = "queued"  # queued|running|success|error|cancelled
    log_lines: list[str] = field(default_factory=list)
    error: str | None = None
    engine: str = "camoufox"
    activation_url: str | None = None
    mail_found_at: float | None = None
    changed_at: float | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    retry_count: int = 0
    # Auth artifacts giữ in-memory (KHÔNG vào to_dict — tránh leak qua SSE).
    _old_password: str | None = field(default=None, repr=False)
    _new_password: str | None = field(default=None, repr=False)
    _refresh_token: str | None = field(default=None, repr=False)
    _client_id: str | None = field(default=None, repr=False)
    _proxy_used: str | None = field(default=None, repr=False)
    _proxy_line: str | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "old_email": self.old_email,
            "new_email": self.new_email,
            "status": self.status,
            "error": self.error,
            "engine": self.engine,
            "activation_url": self.activation_url,
            "mail_found_at": self.mail_found_at,
            "changed_at": self.changed_at,
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


def _parse_account(line: str) -> tuple[str, str]:
    """Parse tài khoản 1Zone: `email|password` hoặc `email<TAB>password`.

    Password có thể chứa `|` (partition lần đầu). Email bắt buộc.
    """
    line = line.strip()
    if not line:
        raise ChangeEmailError("dòng trống — bỏ qua")
    if "|" in line:
        email, _, password = line.partition("|")
    else:
        parts = line.split(None, 1)
        if len(parts) != 2:
            raise ChangeEmailError(
                f"account phải dạng email|password hoặc email<TAB>password: {line!r}"
            )
        email, password = parts
    email = email.strip()
    if "@" not in email:
        raise ChangeEmailError(f"email 1Zone không hợp lệ: {email!r}")
    return email, password.strip()


def _parse_mailbox(line: str) -> OutlookCombo:
    """Parse mailbox mới: `email|pwd|refresh_token|client_id` (OutlookCombo)."""
    return OutlookCombo.parse(line)


# ── Flow helpers ─────────────────────────────────────────────────────────


async def _open_category(page: Any, category: str, *, log: Callable[[str], None]) -> None:
    """Click tab hạng mục (text khớp case-insensitive)."""
    deadline = time.monotonic() + _CLICK_WAIT_SECONDS
    while time.monotonic() < deadline:
        clicked = await page.evaluate(
            "(cat) => { " + _VISIBLE_FN + """
                const btns = [...document.querySelectorAll('button')];
                const btn = btns.find(
                    b => __ceVisible(b)
                      && (b.innerText || '').toUpperCase().includes(cat.toUpperCase())
                );
                if (!btn) return false;
                btn.click();
                return true;
            }""",
            category,
        )
        if clicked:
            log(f"● Mở tab hạng mục: {category}")
            return
        await asyncio.sleep(1.0)
    raise ChangeEmailError(f"không tìm thấy tab hạng mục {category!r}")


async def _click_candidate_vote(
    page: Any, candidate: str, *, log: Callable[[str], None]
) -> None:
    """Tìm candidate card → bấm nút "Bình chọn" trong card đó (poll render)."""
    deadline = time.monotonic() + _CLICK_WAIT_SECONDS
    while time.monotonic() < deadline:
        clicked = await page.evaluate(
            "(candidate) => { " + _VISIBLE_FN + """
                const imgs = [...document.querySelectorAll('img[alt]')];
                for (const img of imgs) {
                    if ((img.getAttribute('alt') || '').trim() !== candidate) continue;
                    const card = img.closest('.candidate-card-dark');
                    if (!card) continue;
                    const btn = [...card.querySelectorAll('button')].find(
                        b => __ceVisible(b) && (b.innerText || '').includes('Bình chọn')
                    );
                    if (btn) { btn.click(); return true; }
                }
                return false;
            }""",
            candidate,
        )
        if clicked:
            log(f"● Bấm Bình chọn — {candidate}")
            return
        await asyncio.sleep(1.0)
    raise ChangeEmailError(f"không tìm thấy nút Bình chọn cho candidate {candidate!r}")


async def _click_vote_gift_package(page: Any, *, log: Callable[[str], None]) -> None:
    """Trong popup vote, chọn gói "1 vote" kiểu Vote tặng (đổi email)."""
    deadline = time.monotonic() + _CLICK_WAIT_SECONDS
    while time.monotonic() < deadline:
        clicked = await page.evaluate(
            "() => { " + _VISIBLE_FN + """
                const btns = [...document.querySelectorAll('button')].filter(__ceVisible);
                const pick = (fn) => btns.find(fn);
                const btn = pick(b => (b.innerText || '').includes('Vote tặng'))
                    || pick(b => {
                        const t = b.innerText || '';
                        return t.includes('1 vote') && t.includes('Chuyển đổi');
                    })
                    || pick(b => (b.innerText || '').trim().startsWith('1 vote'));
                if (!btn) return false;
                btn.click();
                return true;
            }"""
        )
        if clicked:
            log("● Chọn gói 1 vote (Vote tặng)")
            return
        await asyncio.sleep(1.0)
    raise ChangeEmailError("không tìm thấy gói '1 vote' (Vote tặng) trong popup")


async def _click_change_now(page: Any, *, log: Callable[[str], None]) -> None:
    """Bấm "Chuyển đổi ngay" trong panel Vote tặng."""
    deadline = time.monotonic() + _CLICK_WAIT_SECONDS
    while time.monotonic() < deadline:
        clicked = await page.evaluate(
            "() => { " + _VISIBLE_FN + """
                const btns = [...document.querySelectorAll('button')].filter(__ceVisible);
                const btn = btns.find(b => (b.innerText || '').trim() === 'Chuyển đổi ngay')
                    || btns.find(b => (b.innerText || '').includes('Chuyển đổi ngay'));
                if (!btn) return false;
                btn.click();
                return true;
            }"""
        )
        if clicked:
            log("● Bấm Chuyển đổi ngay")
            return
        await asyncio.sleep(1.0)
    raise ChangeEmailError("không tìm thấy nút 'Chuyển đổi ngay'")


async def _fill_new_email(
    page: Any, new_email: str, *, log: Callable[[str], None]
) -> None:
    """Điền email mới vào dialog "Chuyển đổi email"."""
    locator = page.locator('input[placeholder="Địa chỉ email mới"]').first
    try:
        await locator.wait_for(state="visible", timeout=15000)
    except Exception as exc:  # noqa: BLE001
        raise ChangeEmailError(f"dialog 'Chuyển đổi email' không mở: {exc}") from exc
    await locator.click(timeout=10000)
    await locator.press_sequentially(new_email, delay=40)
    log(f"● Điền email mới: {new_email}")


async def _submit_continue(page: Any, *, log: Callable[[str], None]) -> None:
    """Bấm "Tiếp tục" (chờ Turnstile token → nút enable)."""
    deadline = time.monotonic() + _SUBMIT_WAIT_SECONDS
    while time.monotonic() < deadline:
        clicked = await page.evaluate(
            "() => { " + _VISIBLE_FN + """
                const btn = [...document.querySelectorAll('button[type="submit"]')]
                    .filter(__ceVisible)
                    .find(b => (b.innerText || '').includes('Tiếp tục'));
                if (!btn || btn.disabled) return false;
                btn.click();
                return true;
            }"""
        )
        if clicked:
            log("● Bấm Tiếp tục — chờ xác nhận...")
            return
        await asyncio.sleep(1.0)
    raise ChangeEmailError("nút 'Tiếp tục' không sẵn sàng (Turnstile chưa solve?)")


async def _wait_request_sent(page: Any, *, log: Callable[[str], None]) -> None:
    """Chờ popup "Chờ xác nhận" — mail kích hoạt đã được gửi.

    Error hints chỉ được tính khi đi kèm context "đổi email" (email/tài khoản/
    chuyển/đổi) — tránh false-positive từ text khác trên trang (vd
    "Bạn đã sử dụng hết lượt bình chọn").
    """
    deadline = time.monotonic() + _SUBMIT_WAIT_SECONDS
    last_body = ""
    while time.monotonic() < deadline:
        await asyncio.sleep(1.5)
        try:
            last_body = await page.evaluate(
                "() => (document.body ? document.body.innerText : '') || ''"
            )
        except Exception:  # noqa: BLE001
            continue
        low = last_body.lower()
        if "chờ xác nhận" in low or "kiểm tra email kích hoạt" in low:
            log("✓ Đã gửi mail kích hoạt tới email mới")
            return
        for hint, ctx in (
            ("email không hợp lệ", ("email", "chuyển", "đổi")),
            ("đã được sử dụng", ("email", "tài khoản", "chuyển", "đổi")),
            ("đã tồn tại", ("email", "tài khoản", "chuyển")),
            ("không thể chuyển đổi", ("email", "tài khoản", "chuyển", "đổi")),
            ("thất bại", ("email", "chuyển", "đổi", "tài khoản")),
        ):
            if hint in low and any(c in low for c in ctx):
                idx = low.find(hint)
                snippet = last_body[max(0, idx - 150): idx + 250].replace("\n", " ")
                raise ChangeEmailError(
                    f"yêu cầu đổi email bị chặn: {hint!r} … {snippet}"
                )
    raise ChangeEmailError(
        f"không thấy popup 'Chờ xác nhận' sau {int(_SUBMIT_WAIT_SECONDS)}s"
    )


async def _open_change_link(page: Any, url: str, *, log: Callable[[str], None]) -> None:
    """Mở link xác nhận trong CHÍNH phiên browser → chờ "Chuyển đổi thành công"."""
    log("● Mở link xác nhận từ email (cùng phiên browser)")
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    deadline = time.monotonic() + _OPEN_LINK_WAIT_SECONDS
    last_body = ""
    while time.monotonic() < deadline:
        await asyncio.sleep(1.5)
        try:
            last_body = await page.evaluate(
                "() => (document.body ? document.body.innerText : '') || ''"
            )
        except Exception:  # noqa: BLE001
            continue
        low = last_body.lower()
        if "chuyển đổi thành công" in low:
            log("✓ Chuyển đổi thành công")
            return
        for hint in ("hết hạn", "expired", "không hợp lệ", "invalid"):
            if hint in low:
                raise ChangeEmailError(f"link xác nhận lỗi: {hint!r} — {last_body[:300]}")
    raise ChangeEmailError(
        f"không thấy popup 'Chuyển đổi thành công' sau {int(_OPEN_LINK_WAIT_SECONDS)}s"
    )


async def _do_change_email_request(
    page: Any,
    *,
    old_email: str,
    old_password: str,
    new_email: str,
    category: str,
    candidate: str,
    captcha_mode: str,
    yescaptcha_key: str | None,
    proxy: str | None,
    log: Callable[[str], None],
) -> None:
    """B1-B14: login → vote tặng → gửi yêu cầu đổi email (chưa mở link)."""
    log(f"● Mở trang đích {_SITE_URL}")
    await page.goto(_SITE_URL, wait_until="domcontentloaded", timeout=60000)

    await _open_login_dialog(page, log)
    try:
        await _do_login(page, email=old_email, password=old_password, log=log)
    except AlreadyConvertedError:
        raise
    except VoteError as exc:
        raise ChangeEmailError(
            f"{exc} — gợi ý: account có thể đã đổi email ở lần chạy trước "
            "(xem nút Lịch sử) hoặc sai email/password"
        ) from exc
    await _open_category(page, category, log=log)
    await _click_candidate_vote(page, candidate, log=log)
    await _click_vote_gift_package(page, log=log)
    await _click_change_now(page, log=log)
    await _fill_new_email(page, new_email, log=log)
    await _solve_turnstile(
        page,
        mode=captcha_mode,
        yescaptcha_key=yescaptcha_key,
        proxy=proxy,
        log=log,
        site_url=_SITE_URL,
        container_selector=_TURNSTILE_CONTAINER,
    )
    await _submit_continue(page, log=log)
    await _wait_request_sent(page, log=log)


# ── Mail polling ─────────────────────────────────────────────────────────


async def _find_change_email_link(
    combo: OutlookCombo,
    *,
    proxy: str | None,
    since: str | None,
    log: Callable[[str], None],
) -> str | None:
    """Poll hộp thư mới qua Graph → trích link email-change/verify."""
    kwargs: dict[str, Any] = {"timeout": 30.0}
    if proxy:
        kwargs["proxy"] = proxy

    async with httpx.AsyncClient(**kwargs) as client:
        access = await _refresh_access(client, combo)
        for _ in range(3):  # retry list fetch — Graph có thể rate-limit tạm thời
            resp = await client.get(
                "https://graph.microsoft.com/v1.0/me/messages",
                params={
                    "$top": 5,
                    "$orderby": "receivedDateTime desc",
                    "$select": "subject,from,receivedDateTime,body,isRead",
                },
                headers={"Authorization": f"Bearer {access}"},
            )
            if resp.status_code == 200:
                break
            await asyncio.sleep(2.0)
        else:
            raise ChangeEmailError(
                f"Graph API không trả mail để tìm link xác nhận: HTTP {resp.status_code}"
            )

        for msg in resp.json().get("value", []):
            received = msg.get("receivedDateTime") or ""
            if since and received and received < since:
                continue
            subject = (msg.get("subject") or "").lower()
            if not any(k in subject for k in _ACTIVATION_SUBJECTS):
                continue
            body = msg.get("body") or {}
            content = body.get("content") or ""
            if not content:
                content = msg.get("bodyPreview") or ""
            match = _CHANGE_EMAIL_URL_RE.search(content)
            if not match:
                continue
            link = match.group(0).replace("&amp;", "&")
            log(f"[mail] ✓ tìm thấy link xác nhận ({received})")
            return link
    return None


# ── Manager ──────────────────────────────────────────────────────────────


class ChangeEmailManager:
    """Quản lý Đổi Email jobs: queue + workers + SSE (in-memory).

    Ghép cặp account 1Zone + mailbox mới theo thứ tự nhập. Theo dõi account/
    mailbox đã dùng thành công (persist qua Settings Store) để lần chạy sau
    không dùng lại → tránh đổi trùng gây lỗi.
    """

    def __init__(self, *, max_concurrent: int = 1) -> None:
        self._max = max(1, min(30, int(max_concurrent)))
        self._job_timeout: float = 900.0
        self._engine: str = "camoufox"
        self._headless: bool = False
        self._use_proxy: bool = True
        self._candidate: str = _DEFAULT_CANDIDATE
        self._category: str = _DEFAULT_CATEGORY
        self._captcha_mode: str = "auto"
        self._poll_timeout_seconds: float = 600.0
        self._yescaptcha_key: str | None = None
        self._min_seconds: float = 0.0
        self._used_accounts: set[str] = set()
        self._used_mailboxes: set[str] = set()
        # Auto-retry cho lỗi transient (proxy chết, Turnstile timeout, popup chưa hiện...)
        # Mặc định bật để khớp behaviour Reg (JobManager auto_retry). Fatal như
        # "đã được sử dụng" sẽ không retry (xem _is_fatal).
        self._auto_retry: bool = True
        self._auto_retry_max: int = 3
        self._auto_retry_delay: float = 15.0
        self._delayed_requeue_tasks: dict[str, asyncio.Task] = {}

        self.jobs: dict[str, ChangeEmailJob] = {}
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
    def category(self) -> str:
        return self._category

    @property
    def captcha_mode(self) -> str:
        return self._captcha_mode

    @property
    def poll_timeout_seconds(self) -> float:
        return self._poll_timeout_seconds

    @property
    def yescaptcha_key(self) -> str | None:
        return self._yescaptcha_key

    @property
    def min_seconds(self) -> float:
        return self._min_seconds

    @property
    def used_accounts(self) -> list[str]:
        return sorted(self._used_accounts)

    @property
    def used_mailboxes(self) -> list[str]:
        return sorted(self._used_mailboxes)

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

    def set_category(self, value: str) -> None:
        value = (value or "").strip()
        if not value:
            raise ValueError("category không được rỗng")
        self._category = value

    def set_captcha_mode(self, value: str) -> None:
        if value not in ("auto", "click", "yescaptcha", "ezsolver", "camoufox", "inpage", "none"):
            raise ValueError(
                f"captcha_mode phải là auto|click|yescaptcha|ezsolver|camoufox|inpage|none, "
                f"nhận {value!r}"
            )
        self._captcha_mode = value

    def set_poll_timeout(self, value: float) -> None:
        if not (30 <= value <= 3600):
            raise ValueError(f"poll_timeout phải trong [30, 3600], nhận {value}")
        self._poll_timeout_seconds = float(value)

    def set_yescaptcha_key(self, value: str | None) -> None:
        self._yescaptcha_key = (value or "").strip() or None

    def set_min_seconds(self, value: float) -> None:
        if not (0 <= value <= 300):
            raise ValueError(f"min_seconds phải trong [0, 300], nhận {value}")
        self._min_seconds = float(value)

    def set_job_timeout(self, value: float) -> None:
        if not (30 <= value <= 3600):
            raise ValueError(f"job_timeout phải trong [30, 3600], nhận {value}")
        self._job_timeout = float(value)

    def set_auto_retry(self, enabled: bool, *, max_retries: int | None = None, delay: float | None = None) -> None:
        self._auto_retry = bool(enabled)
        if max_retries is not None:
            self._auto_retry_max = max(1, min(max_retries, 10))
        if delay is not None:
            self._auto_retry_delay = max(5.0, min(delay, 120.0))

    @property
    def auto_retry(self) -> bool:
        return self._auto_retry

    @property
    def auto_retry_max(self) -> int:
        return self._auto_retry_max

    @property
    def auto_retry_delay(self) -> float:
        return self._auto_retry_delay

    # ── Auto-retry helpers (mirror JobManager) ──
    _NO_RETRY_KEYS = (
        "đã được sử dụng",
        "đã được chuyển đổi",
        "alreadyconverted",
        "invalid_grant",
        "AADSTS",
        "OutlookComboError",
        "combo dead",
        "email không hợp lệ",
        "thiếu field",
        "camoufox-captcha",
        "chưa cài",
        "chua cai",
        "chưa cấu hình",
        "chua cau hinh",
        "yescaptcha_key",
        "không trích được Turnstile sitekey",
    )

    def _is_fatal(self, error: str | None) -> bool:
        if not error:
            return False
        low = error.lower()
        return any(k.lower() in low for k in self._NO_RETRY_KEYS)

    async def _maybe_auto_retry(self, job: ChangeEmailJob) -> bool:
        if not self._auto_retry:
            return False
        if self._is_fatal(job.error):
            self._job_log(job, "[auto-retry] lỗi fatal — không retry")
            return False
        if job.retry_count >= self._auto_retry_max:
            self._job_log(job, f"[auto-retry] đã retry {job.retry_count}/{self._auto_retry_max} lần — dừng")
            return False
        # Proxy lỗi network → đã mark_dead ở _handle_browser_failure, retry sẽ lấy proxy mới
        job.retry_count += 1
        delay = self._auto_retry_delay * job.retry_count
        self._job_log(job, f"[auto-retry] sẽ retry {job.retry_count}/{self._auto_retry_max} sau {delay:.0f}s")
        job.status = "queued"
        job.error = None
        job.started_at = None
        job.finished_at = None
        self._broadcast_job(job)
        self._schedule_delayed_requeue(job.id, delay)
        return True

    def _schedule_delayed_requeue(self, job_id: str, delay: float) -> None:
        async def _runner() -> None:
            try:
                await asyncio.sleep(delay)
                job = self.jobs.get(job_id)
                if job is None or job.status != "queued":
                    return
                self._job_queue.put_nowait(job_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover
                _log.error("change_email delayed requeue %s failed: %s", job_id, exc)

        existing = self._delayed_requeue_tasks.get(job_id)
        if existing and not existing.done():
            existing.cancel()
        task = asyncio.create_task(_runner())
        self._delayed_requeue_tasks[job_id] = task
        task.add_done_callback(lambda _t, jid=job_id: self._delayed_requeue_tasks.pop(jid, None) if self._delayed_requeue_tasks.get(jid) is _t else None)

    def apply_settings(self, settings: dict) -> None:
        """Hydrate fields từ settings dict (startup boot). Best-effort."""
        if "change_email.max_concurrent" in settings:
            val = int(settings["change_email.max_concurrent"])
            if 1 <= val <= 30:
                self._max = val
        if "change_email.job_timeout" in settings:
            val = float(settings["change_email.job_timeout"])
            if 30 <= val <= 3600:
                self._job_timeout = val
        if "change_email.engine" in settings and settings["change_email.engine"] in (
            "camoufox", "playwright", "chrome", "cloakbrowser"
        ):
            self._engine = settings["change_email.engine"]
        if "change_email.headless" in settings:
            self._headless = bool(settings["change_email.headless"])
        if "change_email.use_proxy" in settings:
            self._use_proxy = bool(settings["change_email.use_proxy"])
        if "change_email.candidate" in settings:
            value = (settings["change_email.candidate"] or "").strip()
            if value:
                self._candidate = value
        if "change_email.category" in settings:
            value = (settings["change_email.category"] or "").strip()
            if value:
                self._category = value
        if "change_email.captcha_mode" in settings and settings["change_email.captcha_mode"] in (
            "auto", "click", "yescaptcha", "ezsolver", "camoufox", "inpage", "none"
        ):
            self._captcha_mode = settings["change_email.captcha_mode"]
        if "change_email.poll_timeout_seconds" in settings:
            val = float(settings["change_email.poll_timeout_seconds"])
            if 30 <= val <= 3600:
                self._poll_timeout_seconds = val
        if "change_email.yescaptcha_key" in settings:
            self._yescaptcha_key = (settings["change_email.yescaptcha_key"] or "").strip() or None
        if "change_email.min_seconds" in settings:
            val = float(settings["change_email.min_seconds"])
            if 0 <= val <= 300:
                self._min_seconds = val
        if "change_email.used_accounts" in settings:
            val = settings["change_email.used_accounts"]
            if isinstance(val, list):
                self._used_accounts = {str(v) for v in val if isinstance(v, str)}
        if "change_email.used_mailboxes" in settings:
            val = settings["change_email.used_mailboxes"]
            if isinstance(val, list):
                self._used_mailboxes = {str(v) for v in val if isinstance(v, str)}
        if "change_email.auto_retry" in settings:
            self._auto_retry = bool(settings["change_email.auto_retry"])
        if "change_email.auto_retry_max" in settings:
            val = int(settings["change_email.auto_retry_max"])
            if 1 <= val <= 10:
                self._auto_retry_max = val
        if "change_email.auto_retry_delay" in settings:
            val = float(settings["change_email.auto_retry_delay"])
            if 5 <= val <= 120:
                self._auto_retry_delay = val

    def to_config_dict(self) -> dict[str, Any]:
        return {
            "max_concurrent": self._max,
            "job_timeout": self._job_timeout,
            "engine": self._engine,
            "headless": self._headless,
            "use_proxy": self._use_proxy,
            "candidate": self._candidate,
            "category": self._category,
            "captcha_mode": self._captcha_mode,
            "poll_timeout_seconds": self._poll_timeout_seconds,
            "yescaptcha_key": self._yescaptcha_key or "",
            "min_seconds": self._min_seconds,
            "auto_retry": self._auto_retry,
            "auto_retry_max": self._auto_retry_max,
            "auto_retry_delay": self._auto_retry_delay,
            "used_accounts": self.used_accounts,
            "used_mailboxes": self.used_mailboxes,
        }

    # ── SSE broadcast ──────────────────────────────────────────────────

    def _broadcast(self, event: dict[str, Any]) -> None:
        from .manager import _sse_mux

        if _sse_mux is not None:
            _sse_mux.publish("change_email", event)

    def _broadcast_job(self, job: ChangeEmailJob) -> None:
        self._broadcast({"type": "job", "job": job.to_dict()})

    def _job_log(self, job: ChangeEmailJob, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        job.log_lines.append(line)
        if len(job.log_lines) > _MAX_LOG_LINES:
            job.log_lines = job.log_lines[-_MAX_LOG_LINES:]
        self._broadcast({"type": "log", "job_id": job.id, "line": line})

    # ── Used tracking ──────────────────────────────────────────────────

    def _repo(self):
        from db import get_change_email_repo, get_engine

        return get_change_email_repo(get_engine())

    def _persist(
        self,
        job: ChangeEmailJob,
        *,
        status: str,
        error: str | None = None,
        activation_url: str | None = None,
    ) -> None:
        """Write-through lịch sử job vào DB (best-effort)."""
        try:
            self._repo().upsert(
                job.old_email,
                job.new_email,
                password=job._old_password,
                status=status,
                error=error,
                engine=job.engine,
                proxy_used=job._proxy_used,
                activation_url=activation_url,
            )
        except Exception as exc:  # noqa: BLE001
            _log.warning("change_email persist fail: %s", exc)

    def list_history(self, *, limit: int = 5000) -> list[dict[str, Any]]:
        """Lịch sử account đã chạy (từ DB) — mới nhất trước."""
        try:
            return self._repo().list_all(limit=limit)
        except Exception as exc:  # noqa: BLE001
            _log.warning("change_email history load fail: %s", exc)
            return []

    def _persist_used(self) -> None:
        """Write-through danh sách đã dùng vào Settings Store (best-effort)."""
        try:
            from db import get_engine, get_settings_repo

            get_settings_repo(get_engine()).bulk_set({
                "change_email.used_accounts": self.used_accounts,
                "change_email.used_mailboxes": self.used_mailboxes,
            })
        except Exception as exc:  # noqa: BLE001
            _log.warning("change_email used persist fail: %s", exc)

    def _mark_used(self, job: ChangeEmailJob) -> None:
        """Đánh dấu account + mailbox đã dùng thành công (tránh dùng lại)."""
        self._used_accounts.add(job.old_email.lower())
        self._used_mailboxes.add(job.new_email.lower())
        self._persist_used()

    def _mark_mailbox_rejected(self, job: ChangeEmailJob, exc: Exception) -> None:
        """Site chặn mailbox (email đã có tài khoản 1Zone) → mark mailbox đã dùng.

        Chỉ đánh dấu MAILBOX (account vẫn dùng được, retry với mailbox khác).
        """
        if "đã được sử dụng" not in str(exc).lower():
            return
        try:
            self._used_mailboxes.add(job.new_email.lower())
            self._persist_used()
            self._job_log(
                job,
                "● Mailbox đã có tài khoản — đánh dấu đã dùng, lần sau không pick lại",
            )
        except Exception as exc2:  # noqa: BLE001
            self._job_log(job, f"mark mailbox used fail: {exc2}")

    def clear_used(self) -> int:
        """Xoá toàn bộ lịch sử đã dùng → cho phép dùng lại account/mailbox."""
        count = len(self._used_accounts) + len(self._used_mailboxes)
        self._used_accounts = set()
        self._used_mailboxes = set()
        self._persist_used()
        return count

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

    def add_jobs(
        self,
        accounts: list[str],
        mailboxes: list[str],
    ) -> tuple[list[ChangeEmailJob], list[str]]:
        """Ghép cặp account 1Zone + mailbox mới → queue jobs.

        Bỏ qua (trả trong ``skipped``): account/mailbox đã dùng thành công,
        đang có job queued/running, hoặc thiếu đầu vào để ghép cặp.
        Trả ``(jobs, skipped)`` — mỗi skipped là ``"lý do: <giá trị>"``.
        """
        active_accounts = {
            j.old_email.lower()
            for j in self.jobs.values()
            if j.status in ("queued", "running")
        }
        active_mailboxes = {
            j.new_email.lower()
            for j in self.jobs.values()
            if j.status in ("queued", "running")
        }

        # Parse + lọc account
        account_items: list[tuple[str, str]] = []
        skipped: list[str] = []
        for raw in accounts:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            try:
                email, password = _parse_account(line)
            except ChangeEmailError as exc:
                skipped.append(f"{str(exc).split(' — ')[0]}: {line[:80]}")
                continue
            if email.lower() in self._used_accounts:
                skipped.append(f"account đã sử dụng: {email}")
                continue
            if email.lower() in active_accounts:
                skipped.append(f"account đang chạy: {email}")
                continue
            account_items.append((email, password))

        # Parse + lọc mailbox
        mailbox_items: list[OutlookCombo] = []
        for raw in mailboxes:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            try:
                combo = _parse_mailbox(line)
            except OutlookComboError as exc:
                skipped.append(f"{str(exc).split(' — ')[0]}: {line[:80]}")
                continue
            if combo.email.lower() in self._used_mailboxes:
                skipped.append(f"mailbox đã sử dụng: {combo.email}")
                continue
            if combo.email.lower() in active_mailboxes:
                skipped.append(f"mailbox đang chạy: {combo.email}")
                continue
            mailbox_items.append(combo)

        if not account_items:
            return [], skipped

        # Ghép cặp tuần tự — thừa account = thiếu mailbox
        pairs = list(zip(account_items, mailbox_items))
        for email, _pw in account_items[len(pairs):]:
            skipped.append(f"thiếu mailbox mới: {email}")

        out: list[ChangeEmailJob] = []
        for (old_email, old_password), combo in pairs:
            jid = uuid.uuid4().hex[:12]
            job = ChangeEmailJob(
                id=jid,
                old_email=old_email,
                new_email=combo.email,
                engine=self._engine,
                _old_password=old_password,
                _new_password=combo.password,
                _refresh_token=combo.refresh_token,
                _client_id=combo.client_id,
            )
            self.jobs[jid] = job
            self.order.append(jid)
            self._job_queue.put_nowait(jid)
            self._broadcast_job(job)
            out.append(job)
        self._ensure_workers()
        return out, skipped

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

    def cancel_job(self, job_id: str) -> bool:
        """Huỷ 1 job riêng: queued → cancelled; running → cancel task.

        Trả True nếu job bị huỷ (hoặc đang được huỷ).
        """
        job = self.jobs.get(job_id)
        if job is None:
            return False
        if job.status == "queued":
            job.status = "cancelled"
            job.finished_at = time.time()
            self._broadcast_job(job)
            return True
        if job.status == "running":
            task = self._tasks.get(job_id)
            if task:
                task.cancel()
            return True
        return False

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
        """Success line: ``mailcu|mailmoi|pass`` (password đăng nhập giữ nguyên)."""
        success: list[str] = []
        errors: list[str] = []
        for jid in self.order:
            job = self.jobs.get(jid)
            if not job:
                continue
            if job.status == "success":
                success.append(f"{job.old_email}|{job.new_email}|{job._old_password or ''}")
            elif job.status == "error":
                errors.append(f"{job.old_email}  →  {job.error or 'unknown'}")
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

    async def _run_job(self, job: ChangeEmailJob) -> None:
        job.status = "running"
        job.started_at = time.time()
        start_mono = time.monotonic()
        self._broadcast_job(job)
        self._job_log(job, "● Bắt đầu job")
        self._persist(job, status="running")

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
        except asyncio.CancelledError:
            # User huỷ job / Stop All — mark cancelled rồi re-raise để worker
            # loop biết task đã kết thúc (không pick lại).
            job.status = "cancelled"
            job.error = "cancelled by user"
            self._job_log(job, "✗ Job bị huỷ")
            raise
        except AlreadyConvertedError as exc:
            converted = getattr(exc, "converted_email", None)
            if converted and converted.lower() != job.new_email.lower():
                self._job_log(
                    job,
                    f"● Lưu ý: đã chuyển sang {converted} (khác mailbox yêu cầu {job.new_email}) — output theo thực tế",
                )
                job.new_email = converted
            self._job_log(
                job,
                f"✓ Tài khoản đã được chuyển đổi trước đó sang {job.new_email} — đưa output luôn",
            )
            job.status = "success"
            job.error = None
            try:
                self._mark_used(job)
                self._job_log(job, "● Đã đánh dấu account + mailbox đã dùng (already-converted)")
            except Exception as exc2:  # noqa: BLE001
                self._job_log(job, f"mark used fail: {exc2}")
        except asyncio.TimeoutError:
            job.error = f"job timeout sau {int(self._job_timeout)}s"
            job.status = "error"
            self._job_log(job, f"✗ {job.error}")
            await self._handle_browser_failure(job, TimeoutError(job.error))
            if await self._maybe_auto_retry(job):
                self._job_log(job, "↻ Auto-retry đã requeue job (timeout)")
        except (ChangeEmailError, VoteError, EventistaError) as exc:
            job.error = _short_error(str(exc))
            job.status = "error"
            self._job_log(job, f"✗ {job.error}")
            # Mailbox bị site chặn ("Email đã được sử dụng") → không bao giờ đổi
            # sang được → đánh dấu đã dùng để lần chạy sau không pick lại.
            self._mark_mailbox_rejected(job, exc)
            # Các lỗi transient như Turnstile, popup, tab, proxy... sẽ auto-retry
            # nếu còn quota (fatal như "đã được sử dụng" đã bị _is_fatal chặn)
            await self._handle_browser_failure(job, exc)
            if await self._maybe_auto_retry(job):
                self._job_log(job, "↻ Auto-retry đã requeue job")
        except Exception as exc:  # noqa: BLE001
            await self._handle_browser_failure(job, exc)
            job.error = _short_error(f"{type(exc).__name__}: {exc}")
            job.status = "error"
            self._job_log(job, f"✗ {job.error}")
            if await self._maybe_auto_retry(job):
                self._job_log(job, "↻ Auto-retry đã requeue job (browser error)")
        else:
            if proxy and self._min_seconds > 0:
                elapsed = time.monotonic() - start_mono
                wait = self._min_seconds - elapsed
                if wait > 0:
                    self._job_log(
                        job,
                        f"● Flow xong sau {elapsed:.0f}s — chờ thêm {wait:.0f}s "
                        f"cho đủ {int(self._min_seconds)}s",
                    )
                    await asyncio.sleep(wait)
            job.status = "success"
            self._job_log(job, "✓ Đổi email flow hoàn thành")
            try:
                self._mark_used(job)
                self._job_log(job, "● Đã đánh dấu account + mailbox đã dùng")
            except Exception as exc:  # noqa: BLE001
                self._job_log(job, f"mark used fail (best-effort): {exc}")
        finally:
            job.finished_at = time.time()
            self._broadcast_job(job)
            # Lịch sử DB: status cuối (success/error/cancelled...).
            if job.status != "running":
                self._persist(job, status=job.status, error=job.error)

    async def _handle_browser_failure(self, job: ChangeEmailJob, exc: Exception) -> None:
        """Lỗi browser/network → mark proxy chết (reuse cơ chế Eventista/Vote)."""
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

    async def _run_job_inner(self, job: ChangeEmailJob, *, proxy: str | None) -> None:
        if not (job._old_password and job._new_password and job._refresh_token and job._client_id):
            raise ChangeEmailError("job thiếu field bắt buộc — không chạy được")
        combo = OutlookCombo(
            email=job.new_email,
            password=job._new_password,
            refresh_token=job._refresh_token,
            client_id=job._client_id,
        )
        since = (
            datetime.now(timezone.utc) - timedelta(seconds=_SINCE_MARGIN_SECONDS)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        engine = _resolve_browser_engine(
            self._engine,
            log=lambda m: self._job_log(job, m),
        )
        job.engine = engine

        page, _handle, close = await _launch_browser(
            engine,
            headless=self._headless,
            proxy=proxy,
            camoufox_captcha=(engine == "camoufox" and self._captcha_mode == "camoufox"),
        )
        try:
            await _do_change_email_request(
                page,
                old_email=job.old_email,
                old_password=job._old_password,
                new_email=job.new_email,
                category=self._category,
                candidate=self._candidate,
                captcha_mode=self._captcha_mode,
                yescaptcha_key=self._yescaptcha_key,
                proxy=proxy,
                log=lambda m: self._job_log(job, m),
            )

            # ── Poll mail hộp thư MỚI tìm link xác nhận ──
            # Đọc mail qua Graph LUÔN chạy trực tiếp (không proxy) — proxy
            # xoay IP hay chặn kết nối tới graph.microsoft.com gây
            # ConnectTimeout spam, trong khi đọc mail local direct không lỗi.
            self._job_log(
                job,
                "● Đợi mail kích hoạt — poll Graph trực tiếp (không proxy) "
                f"tối đa {int(self._poll_timeout_seconds)}s",
            )
            link: str | None = None
            deadline = time.monotonic() + self._poll_timeout_seconds
            last_err: str | None = None
            while time.monotonic() < deadline:
                try:
                    link = await _find_change_email_link(
                        combo, proxy=None, since=since,
                        log=lambda m: self._job_log(job, m),
                    )
                    if link:
                        break
                except OutlookComboError as exc:
                    last_err = str(exc)
                    self._job_log(job, f"✗ [mail] combo dead: {last_err}")
                    break
                except ChangeEmailError as exc:
                    last_err = str(exc)
                    self._job_log(job, f"✗ [mail] {last_err}")
                    break
                except Exception as exc:  # noqa: BLE001
                    last_err = f"{type(exc).__name__}: {exc}"
                    self._job_log(job, f"● [mail] lỗi tạm thời — retry: {last_err}")
                await asyncio.sleep(_POLL_INTERVAL_SECONDS)

            if not link:
                raise ChangeEmailError(
                    last_err
                    or f"không tìm thấy mail kích hoạt trong {int(self._poll_timeout_seconds)}s"
                )
            job.activation_url = link
            job.mail_found_at = time.time()
            self._persist(job, status="running", activation_url=link)

            # ── Mở link trong CHÍNH phiên browser đang chạy ──
            await _open_change_link(page, link, log=lambda m: self._job_log(job, m))
        finally:
            try:
                await close()
            except Exception as exc:  # noqa: BLE001
                self._job_log(job, f"close browser: {exc}")

        job.changed_at = time.time()
        job.error = None


# Singleton
_change_email_manager: ChangeEmailManager | None = None


def get_change_email_manager() -> ChangeEmailManager:
    global _change_email_manager  # noqa: PLW0603
    if _change_email_manager is None:
        _change_email_manager = ChangeEmailManager(max_concurrent=1)
    return _change_email_manager