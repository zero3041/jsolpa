"""Reg Eventista — tự động đăng ký tài khoản trên tinhhasayhi.1vote.vn.

Mỗi job = 1 combo Outlook (`email|password|refresh_token|client_id`):
  1. Browser (Camoufox mặc định / Playwright Chromium / CloakBrowser nếu cài)
     mở site → Đăng nhập → "Đăng ký ngay" → điền email + password random →
     đồng ý điều khoản → Turnstile (auto/yescaptcha/none) → submit.
  2. Poll hòm thư qua Graph API (reuse `_refresh_access` từ mail_reader) cho
     tới khi thấy email "Activate your account" → trích link
     `https://account.faniesta.com/v2/auth/accounts/verify-email?token=...`.
  3. Mở link kích hoạt bằng browser → account activated.

Persistence (DB):
  - `eventista_accounts`: lịch sử từng account (status/error/activation_url).
  - `outlook_combos.tag_eventista`: combo đã activated → tag=1 (không pick lại).
Proxy: chạy qua proxy pool config (giống Reg/UPI, qua `_resolve_job_proxy`).
In-memory jobs (không persist — lifecycle ngắn như UpiJobManager).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import secrets
import string
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx

from mail_providers import OutlookCombo, OutlookComboError
from .mail_reader import _refresh_access

_log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────

_SITE_URL = "https://tinhhasayhi.1vote.vn"
_ACTIVATION_URL_RE = re.compile(
    r"https://account\.faniesta\.com/v2/auth/accounts/verify-email\?token=[^\"'\s<>]+"
)
# Email kích hoạt: subject chứa 1 trong các từ khóa này.
_ACTIVATION_SUBJECTS = (
    "activate your account",
    "activate account",
    "kích hoạt tài khoản",
    "xác nhận email",
    "[1zone]",
)
# Thông báo thành công / lỗi trên site (chứa 1 trong các cụm).
_SUCCESS_HINTS = ("đăng ký thành công", "kiểm tra email", "verify-account", "check email")
_ERROR_HINTS = ("đã tồn tại", "already exists", "email không hợp lệ", "lỗi", "error")

_DEFAULT_PASSWORD_LEN = 14
_PASSWORD_CHARS = string.ascii_letters + string.digits
_PASSWORD_SPECIALS = "!@#$%^&*"
# Thời gian chờ tối đa submit form → xuất hiện thông báo thành công.
_REGISTER_WAIT_SECONDS = 60.0
# Khoảng delay giữa các lần poll mail.
_POLL_INTERVAL_SECONDS = 12.0
# Giới hạn log lines giữ trong job.
_MAX_LOG_LINES = 2000

# YesCaptcha API endpoints (không phụ thuộc chatgpt_camoufox — cài thủ công).
_YESCAPTCHA_CREATE_URL = "https://api.yescaptcha.com/createTask"
_YESCAPTCHA_RESULT_URL = "https://api.yescaptcha.com/getTaskResult"
_YESCAPTCHA_TIMEOUT = 120.0
_CLOAKBROWSER_INSTALL_ATTEMPTED = False


def _short_error(msg: str, limit: int = 160) -> str:
    """Rút gọn error cho job row: lấy dòng đầu tiên (bỏ "Call log:..." của
    Playwright), cắt theo limit. Giữ nguyên nếu ngắn."""
    first = (msg or "").splitlines()[0] if (msg or "").splitlines() else ""
    return first[:limit]


def _load_hybrid_env() -> dict[str, str]:
    """Đọc gpt_signup_hybrid/.env (seed key YesCaptcha nếu chưa set trong UI)."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    values: dict[str, str] = {}
    if not env_path.exists():
        return values
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        values[key.strip()] = val.strip().strip("'\"")
    return values


_HYBRID_ENV = _load_hybrid_env()


def _env(key: str, default: str) -> str:
    """Ưu tiên: os.environ > .env file > default."""
    return os.environ.get(key) or _HYBRID_ENV.get(key) or default


_YESCAPTCHA_ENV_KEY = _env("YESCAPTCHA_CLIENT_KEY", "") or None


class EventistaError(Exception):
    """Lỗi nghiệp vụ Eventista — message hiển thị thẳng trong job.error."""


# ── Job model ────────────────────────────────────────────────────────────


@dataclass
class EventistaJob:
    id: str
    email: str
    password: str
    status: str = "queued"  # queued|running|success|error|cancelled
    log_lines: list[str] = field(default_factory=list)
    error: str | None = None
    engine: str = "camoufox"
    activation_url: str | None = None
    mail_found_at: float | None = None
    activated_at: float | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    # Auth artifacts giữ in-memory (KHÔNG vào to_dict — tránh leak qua SSE):
    # refresh_token/client_id để poll mail activation qua Graph API.
    _refresh_token: str | None = field(default=None, repr=False)
    _client_id: str | None = field(default=None, repr=False)
    _proxy_used: str | None = field(default=None, repr=False)
    _proxy_line: str | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "email": self.email,
            "status": self.status,
            "error": self.error,
            "engine": self.engine,
            "activation_url": self.activation_url,
            "mail_found_at": self.mail_found_at,
            "activated_at": self.activated_at,
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
        d["password"] = self.password
        d["log_lines"] = list(self.log_lines)
        return d


# ── Password ─────────────────────────────────────────────────────────────


def generate_password() -> str:
    """Tạo password đủ mạnh: viết hoa + viết thường + số + ký tự đặc biệt."""
    length = _DEFAULT_PASSWORD_LEN
    # Guarantee 1 mỗi loại, phần còn lại ngẫu nhiên từ tổ hợp.
    pool = _PASSWORD_CHARS + _PASSWORD_SPECIALS
    chars = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice(_PASSWORD_SPECIALS),
    ]
    chars += [secrets.choice(pool) for _ in range(length - 4)]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


# ── Browser helpers ──────────────────────────────────────────────────────


def _proxy_to_camoufox_dict(proxy: str | None) -> dict[str, Any] | None:
    """Parse proxy URL (`http://user:pass@host:port`) → dict Camoufox cần.

    Camoufox 0.4.x yêu cầu mapping {server, username, password} — truyền
    string sẽ nổ ``Proxy() argument after ** must be a mapping``.

    Lưu ý: proxy từ pool được ``materialize_proxy`` URL-encode credential
    (``quote(safe="")`` — `=` → `%3D`). Phải unquote trước khi đưa vào dict,
    nếu không Camoufox gửi password literal ``%3D`` → proxy refuse connection.
    """
    if not proxy:
        return None
    from urllib.parse import unquote, urlparse

    parsed = urlparse(proxy if "://" in proxy else f"http://{proxy}")
    if not parsed.hostname:
        return None
    server = f"{parsed.scheme}://{parsed.hostname}"
    if parsed.port:
        server += f":{parsed.port}"
    result: dict[str, Any] = {"server": server, "username": None, "password": None}
    if parsed.username:
        result["username"] = unquote(parsed.username)
    if parsed.password:
        result["password"] = unquote(parsed.password)
    return result


def _resolve_browser_engine(
    engine: str,
    *,
    log: Callable[[str], None] | None = None,
) -> str:
    """Resolve engine thực tế trước khi launch browser.

    CloakBrowser là engine tuỳ chọn; nếu package chưa cài thì fallback sang
    Playwright Chromium để job vẫn chạy được.
    """
    if engine != "cloakbrowser":
        return engine
    global _CLOAKBROWSER_INSTALL_ATTEMPTED  # noqa: PLW0603
    try:
        from cloakbrowser.async_api import async_playwright  # type: ignore
    except ImportError:
        if not _CLOAKBROWSER_INSTALL_ATTEMPTED:
            _CLOAKBROWSER_INSTALL_ATTEMPTED = True
            if log:
                log(
                    "CloakBrowser chưa cài — đang thử tự cài `pip install cloakbrowser` "
                    "(binary ~130MB, có thể mất vài phút)"
                )
            try:
                subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "pip",
                        "install",
                        "cloakbrowser",
                        "--disable-pip-version-check",
                        "--no-input",
                    ],
                    check=True,
                )
                from cloakbrowser.async_api import async_playwright  # type: ignore
                if log:
                    log("CloakBrowser đã được cài xong — tiếp tục dùng CloakBrowser")
                return engine
            except Exception as exc:  # noqa: BLE001
                if log:
                    log(
                        f"CloakBrowser auto-install thất bại — fallback sang Playwright Chromium: {exc}"
                    )
                return "playwright"
        if log:
            log(
                "CloakBrowser chưa cài — fallback sang Playwright Chromium"
            )
        return "playwright"
    return engine


async def _launch_browser(
    engine: str,
    *,
    headless: bool,
    proxy: str | None,
    camoufox_captcha: bool = False,
) -> tuple[Any, Any, Callable[[], Awaitable[None]]]:
    """Launch browser theo engine → (page, browser_handle, close_coro).

    Engine:
      - ``camoufox``: AsyncCamoufox (mặc định). handle = AsyncCamoufox instance.
      - ``playwright``: Playwright Chromium. handle = (pw, browser, context).
      - ``cloakbrowser``: drop-in Playwright replacement (pass Turnstile).
        Cần `pip install cloakbrowser` — chưa cài → EventistaError rõ ràng.

    ``camoufox_captcha=True`` (engine=camoufox + captcha_mode=camoufox): thêm
    config bắt buộc của camoufox-captcha — `forceScopeAccess` (truy cập closed
    shadow root chứa checkbox Turnstile) + `disable_coop`.

    Raises:
        EventistaError: engine không hợp lệ / thư viện chưa cài.
    """
    if engine == "camoufox":
        try:
            from camoufox.async_api import AsyncCamoufox
        except ImportError as exc:  # pragma: no cover — phụ thuộc env
            raise EventistaError("Camoufox chưa cài (pip install camoufox)") from exc
        proxy_kwargs: dict[str, Any] = {}
        if proxy:
            proxy_kwargs["proxy"] = _proxy_to_camoufox_dict(proxy)
        solver_kwargs: dict[str, Any] = {}
        if camoufox_captcha:
            solver_kwargs = {
                "config": {"forceScopeAccess": True},
                "disable_coop": True,
            }
        cf = AsyncCamoufox(
            headless=headless,
            geoip=bool(proxy),
            **proxy_kwargs,
            **solver_kwargs,
        )
        browser = await cf.__aenter__()
        page = await browser.new_page()

        async def close() -> None:
            await cf.__aexit__(None, None, None)

        return page, cf, close

    if engine in ("playwright", "cloakbrowser", "chrome"):
        if engine == "cloakbrowser":
            try:
                from cloakbrowser.async_api import async_playwright  # type: ignore
            except ImportError as exc:
                raise EventistaError(
                    "CloakBrowser chưa cài — chạy `pip install cloakbrowser` "
                    "(cần tải binary ~130MB)"
                ) from exc
        else:
            from playwright.async_api import async_playwright  # type: ignore

        pw = await async_playwright().start()
        if engine == "chrome":
            # Chrome THẬT (google-chrome-stable) qua Playwright — cần stealth:
            # Playwright mặc định bật `--enable-automation` + navigator.webdriver
            # → Cloudflare Turnstile detect và không cấp token. Tắt cả 2.
            browser = await pw.chromium.launch(
                headless=headless,
                channel="chrome",
                ignore_default_args=["--enable-automation"],
                args=["--disable-blink-features=AutomationControlled"],
            )
        else:
            browser = await pw.chromium.launch(headless=headless)
        proxy_cfg: dict[str, Any] | None = None
        if proxy:
            proxy_cfg = _proxy_to_camoufox_dict(proxy)
        context = await browser.new_context(
            proxy=proxy_cfg,
            locale="vi-VN",
            viewport={"width": 1366, "height": 900},
        )
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        page = await context.new_page()

        async def close() -> None:
            await context.close()
            await browser.close()
            await pw.stop()

        return page, (pw, browser, context), close

    raise EventistaError(f"engine không hợp lệ: {engine!r}")


async def _click_by_text(page: Any, text: str, *, timeout: float = 15.0) -> bool:
    """Click phần tử có text khớp (case-insensitive, partial). True nếu clicked."""
    try:
        locator = page.get_by_text(text, exact=False).first
        await locator.click(timeout=timeout * 1000)
        return True
    except Exception:  # noqa: BLE001 — probe, không crash
        return False


async def _sitekey(page: Any) -> str | None:
    """Trích Turnstile sitekey từ trang: attribute data-sitekey, regex script,
    hoặc scan JS chunks (Next.js bundle — sitekey nằm trong JS, không trong HTML)."""
    try:
        value = await page.evaluate(
            "() => document.querySelector('#cf-turnstile')?.getAttribute('data-sitekey') || ''"
        )
        if value:
            return str(value).strip() or None
    except Exception:  # noqa: BLE001
        pass
    try:
        html = await page.content()
    except Exception:  # noqa: BLE001
        return None
    m = re.search(r"sitekey\s*[:=]\s*['\"]([A-Za-z0-9_-]{10,})['\"]", html)
    if m:
        return m.group(1)
    m = re.search(r"0x[A-Za-z0-9_]{15,}", html)
    if m:
        return m.group(0)
    try:
        srcs = re.findall(r'src="([^"]+\.js[^"]*)"', html)
        for src in srcs:
            if not src.startswith("http"):
                src = "https://tinhhasayhi.1vote.vn" + src
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(src)
                    resp.raise_for_status()
                    m = re.search(r"0x[A-Za-z0-9_]{15,}", resp.text)
                    if m:
                        return m.group(0)
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass
    return None


async def _solve_turnstile(
    page: Any,
    *,
    mode: str,
    yescaptcha_key: str | None,
    proxy: str | None = None,
    log: Callable[[str], None],
) -> None:
    """Xử lý Turnstile theo mode.

    - ``auto``: đợi hidden input `cf-turnstile-response` có giá trị (widget
      invisible/auto-solve). Có click thử checkbox iframe nếu thấy.
    - ``click``: tự click checkbox Turnstile (click-to-verify) → chờ token.
    - ``yescaptcha``: solve qua YesCaptcha API (TurnstileTaskProxyless) →
      inject token vào hidden input.
    - ``ezsolver``: solve qua EzSolver (Chrome thật local service, dùng cùng
      proxy nếu có) → inject token vào hidden input.
    - ``camoufox``: solve qua camoufox-captcha ngay trong page (click checkbox
      trong closed shadow root của widget Turnstile) → chờ token tự điền.
    - ``inpage``: inject widget Turnstile riêng ngay trong page đăng ký →
      auto-solve hoặc click checkbox → inject token. Cùng IP + fingerprint.
    - ``none``: bỏ qua — submit thẳng (site tự pass hoặc captcha không chặn).
    """
    if mode == "none":
        log("[captcha] bỏ qua captcha (mode=none)")
        return

    if mode == "click":
        log("● Chờ captcha Turnstile hoàn thành...")
        await _wait_turnstile_token(page, log=log, try_click=True)
        return

    if mode == "yescaptcha":
        if not yescaptcha_key:
            raise EventistaError("captcha_mode=yescaptcha nhưng chưa cấu hình yescaptcha_key")
        sitekey = await _sitekey(page)
        if not sitekey:
            raise EventistaError("không trích được Turnstile sitekey từ trang")
        token = await _yescaptcha_solve(yescaptcha_key, _SITE_URL, sitekey, log=log)
        await page.evaluate(
            """(token) => {
                const el = document.querySelector('input[name="cf-turnstile-response"]');
                if (el) el.value = token;
            }""",
            token,
        )
        log("[captcha] yescaptcha: token injected")
        return

    if mode == "ezsolver":
        log("● EzSolver: solve Turnstile qua Chrome thật...")
        sitekey = await _sitekey(page)
        if not sitekey:
            raise EventistaError("không trích được Turnstile sitekey từ trang")
        token = await _ezsolver_solve(sitekey, _SITE_URL, proxy=proxy, log=log)
        await page.evaluate(
            """(token) => {
                const el = document.querySelector('input[name="cf-turnstile-response"]');
                if (el) el.value = token;
            }""",
            token,
        )
        log("● EzSolver: token injected")
        return

    if mode == "inpage":
        log("● In-page: solve Turnstile ngay trong browser đăng ký...")
        sitekey = await _sitekey(page)
        if not sitekey:
            raise EventistaError("không trích được Turnstile sitekey từ trang")
        await _solve_turnstile_inpage(page, sitekey, log=log)
        return

    if mode == "camoufox":
        log("● camoufox-captcha: click checkbox Turnstile trong shadow root...")
        await _solve_turnstile_camoufox(page, log=log)
        return

    # mode == "auto" — đợi widget tự solve (tối đa 120s).
    log("● Chờ captcha Turnstile hoàn thành...")
    await _wait_turnstile_token(page, log=log)


async def _solve_turnstile_inpage(
    page: Any,
    sitekey: str,
    *,
    log: Callable[[str], None],
    timeout: float = 120.0,
) -> None:
    """Solve Turnstile ngay trong page hiện tại (cùng browser/IP/fingerprint).

    Kỹ thuật EzSolver: inject widget Turnstile riêng (`turnstile.render` vào
    `#_ts_box`) → widget invisible tự solve hoặc click checkbox iframe →
    poll `window._tsToken` → ghi token vào hidden input của site.

    Lý do không tách browser riêng: token solve từ IP khác IP submit có thể
    bị site reject; inject cùng page thì IP + fingerprint khớp hoàn toàn.
    """
    try:
        injected = await page.evaluate(
            """() => {
                if (document.getElementById('_ts_box')) return true;
                window._tsToken = null;
                const wrap = document.createElement('div');
                wrap.id = '_ts_box';
                wrap.style = 'position:fixed;top:20px;left:20px;z-index:2147483647;';
                document.body.appendChild(wrap);
                window._tsLoad = function () {
                    turnstile.render('#_ts_box', {
                        sitekey: window._tsSitekey,
                        callback: function(token) { window._tsToken = token; }
                    });
                };
                const s = document.createElement('script');
                s.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?onload=_tsLoad&render=explicit';
                s.async = true;
                document.head.appendChild(s);
                return true;
            }"""
        )
        await page.evaluate(
            "(key) => { window._tsSitekey = key; }",
            sitekey,
        )
        # api.js?onload=_tsLoad tự gọi _tsLoad() sau khi load xong (cơ chế
        # callback của Cloudflare) — không gọi thủ công vội, dễ "turnstile
        # is not defined".
        log("● In-page: widget Turnstile injected — chờ solve...")
        await asyncio.sleep(5.0)

        async def _token() -> str:
            try:
                v = await page.evaluate(
                    """() => {
                        if (window._tsToken) return window._tsToken;
                        const el = document.querySelector('input[name="cf-turnstile-response"]');
                        return (el && el.value) ? el.value : '';
                    }"""
                )
                return str(v or "")
            except Exception:  # noqa: BLE001
                return ""

        token = await _token()
        if not token:
            # Click checkbox iframe nếu render (managed widget).
            try:
                await page.locator(
                    'iframe[src*="challenges.cloudflare.com"]'
                ).first.click(timeout=10000)
                log("● In-page: đã click checkbox Turnstile")
            except Exception:  # noqa: BLE001
                log("● In-page: widget invisible hoặc iframe chưa render")

        # Poll token — click lại nếu 8s chưa có (giống EzSolver loop).
        deadline = time.monotonic() + timeout
        clicked = 0
        last_click = 0.0
        while time.monotonic() < deadline:
            token = await _token()
            if token:
                break
            now = time.monotonic()
            if now - last_click > 8 and clicked < 3:
                try:
                    await page.locator(
                        'iframe[src*="challenges.cloudflare.com"]'
                    ).first.click(timeout=5000)
                    clicked += 1
                    last_click = now
                    log(f"● In-page: click checkbox lần {clicked}")
                except Exception:  # noqa: BLE001
                    await asyncio.sleep(1.0)
                    continue
            await asyncio.sleep(0.5)
        if not token:
            raise EventistaError(f"In-page Turnstile không solve trong {int(timeout)}s")

        await page.evaluate(
            """(token) => {
                const el = document.querySelector('input[name="cf-turnstile-response"]');
                if (el) el.value = token;
            }""",
            token,
        )
        log("● In-page: Turnstile solved — token injected")
    except EventistaError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise EventistaError(f"In-page Turnstile fail: {exc}") from exc


async def _solve_turnstile_camoufox(
    page: Any,
    *,
    log: Callable[[str], None],
    timeout: float = 120.0,
) -> None:
    """Solve Turnstile bằng camoufox-captcha ngay trong page hiện tại.

    Library này click checkbox Turnstile ẩn trong **closed shadow root**
    (bình thường Playwright không truy cập được). Yêu cầu engine=camoufox
    launch với ``forceScopeAccess`` + ``disable_coop`` (xem _launch_browser).

    Sau khi click + verify xong, Cloudflare tự điền token vào hidden input
    → chờ token như mode click/auto.
    """
    try:
        from camoufox_captcha import solve_captcha  # type: ignore
    except ImportError as exc:
        raise EventistaError(
            "captcha_mode=camoufox nhưng chưa cài camoufox-captcha "
            "(pip install camoufox-captcha)"
        ) from exc

    container = page.locator("#cf-turnstile").first
    try:
        await container.wait_for(state="attached", timeout=30000)
    except Exception as exc:  # noqa: BLE001
        raise EventistaError(f"không tìm thấy #cf-turnstile: {exc}") from exc
    handle = await container.element_handle()

    solved = await solve_captcha(
        handle,
        captcha_type="cloudflare",
        challenge_type="turnstile",
        solve_attempts=2,
        wait_checkbox_attempts=8,
        wait_checkbox_delay=3,
    )
    log(f"● camoufox-captcha: solver → {'OK' if solved else 'không tìm thấy checkbox'}")

    # Widget invisible/click xong → chờ token tự điền vào hidden input.
    await _wait_turnstile_token(page, log=log, timeout=timeout)


async def _wait_turnstile_token(
    page: Any,
    *,
    log: Callable[[str], None],
    timeout: float = 120.0,
    try_click: bool = False,
) -> None:
    """Chờ hidden input `cf-turnstile-response` có token.

    Site dùng Turnstile managed widget — token tự điền vào hidden input,
    iframe checkbox render không đồng bộ (lúc đầu #cf-turnstile chỉ có
    hidden input, iframe xuất hiện sau). ``try_click`` (mode click): chờ
    iframe xuất hiện rồi click checkbox → chờ token.
    """
    try:
        # Token đã có sẵn (widget invisible/auto-solve)?
        has = await page.evaluate(
            """() => {
                const el = document.querySelector('input[name="cf-turnstile-response"]');
                return !!(el && el.value && el.value.length > 0);
            }"""
        )
        if has:
            log("● Turnstile solved")
            return

        if try_click:
            # Chờ iframe checkbox render (site render widget bất đồng bộ).
            iframe_sel = 'iframe[src*="challenges.cloudflare.com"]'
            try:
                await page.wait_for_selector(iframe_sel, timeout=30000)
                log("● Widget Turnstile hiện — click checkbox")
                await page.locator(iframe_sel).first.click(timeout=10000)
                log("● Đã click checkbox Turnstile")
            except Exception as exc:  # noqa: BLE001
                log(f"● Widget iframe không render/click fail: {exc}")
        else:
            # mode auto — click thử nếu iframe đã có (không bắt buộc).
            try:
                await page.locator(
                    'iframe[src*="challenges.cloudflare.com"]'
                ).first.click(timeout=3000)
            except Exception:  # noqa: BLE001 — widget invisible/managed
                pass

        # wait_for_function nhận timeout theo MILLISECONDS.
        deadline_ms = int(timeout * 1000)
        poll_every = 15.0
        polled = 0.0
        while True:
            try:
                await page.wait_for_function(
                    """() => {
                        const el = document.querySelector('input[name="cf-turnstile-response"]');
                        return el && el.value && el.value.length > 0;
                    }""",
                    timeout=min(deadline_ms, 15000),
                )
                log("● Turnstile solved")
                return
            except Exception:  # noqa: BLE001 — chưa có token, poll tiếp
                pass
            polled += poll_every
            if polled >= timeout:
                break
            log(f"● Vẫn đang chờ token Turnstile... ({int(polled)}s/{int(timeout)}s)")
        raise EventistaError(f"Turnstile không solve trong {int(timeout)}s")
    except EventistaError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise EventistaError(
            f"Turnstile không solve trong {int(timeout)}s: {exc}"
        ) from exc


async def _yescaptcha_solve(
    client_key: str,
    website_url: str,
    website_key: str,
    *,
    log: Callable[[str], None],
) -> str:
    """CreateTask TurnstileTaskProxyless + poll getTaskResult → token.

    Raises:
        EventistaError: create fail / solution không có token / timeout.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(_YESCAPTCHA_CREATE_URL, json={
            "clientKey": client_key,
            "task": {
                "type": "TurnstileTaskProxyless",
                "websiteURL": website_url,
                "websiteKey": website_key,
            },
        })
        resp.raise_for_status()
        data = resp.json()
        if data.get("errorId") != 0:
            raise EventistaError(f"YesCaptcha create fail: {data.get('errorDescription') or data}")
        task_id = data["taskId"]
        log(f"[captcha] yescaptcha: task {task_id} created")

        deadline = time.monotonic() + _YESCAPTCHA_TIMEOUT
        while time.monotonic() < deadline:
            await asyncio.sleep(3.0)
            res = await client.post(_YESCAPTCHA_RESULT_URL, json={
                "clientKey": client_key,
                "taskId": task_id,
            })
            res.raise_for_status()
            res_data = res.json()
            if res_data.get("errorId") != 0:
                raise EventistaError(
                    f"YesCaptcha result fail: {res_data.get('errorDescription') or res_data}"
                )
            if res_data.get("status") == "ready":
                token = ((res_data.get("solution") or {}).get("token") or "").strip()
                if not token:
                    raise EventistaError("YesCaptcha ready nhưng không có token")
                return token
        raise EventistaError(f"YesCaptcha timeout sau {int(_YESCAPTCHA_TIMEOUT)}s")


# ── EzSolver (Chrome thật + nodriver, local service) ─────────────────────

_EZSOLVER_DIR = Path(os.environ.get("EZSOLVER_DIR", str(Path.home() / "tools" / "EzSolver")))
_EZSOLVER_HOST = os.environ.get("EZSOLVER_HOST", "http://127.0.0.1:8191")
_EZSOLVER_SERVICE_FILE = _EZSOLVER_DIR / "service.py"
_EZSOLVER_MAX_WORKERS = int(os.environ.get("EZSOLVER_MAX_WORKERS", "2"))
_ezsolver_proc: subprocess.Popen | None = None


def _ezsolver_ensure_service() -> None:
    """Start local EzSolver HTTP service nếu chưa chạy (lazy, 1 lần)."""
    global _ezsolver_proc
    if _ezsolver_proc is not None and _ezsolver_proc.poll() is None:
        return
    if not _EZSOLVER_SERVICE_FILE.exists():
        raise EventistaError(
            f"chưa clone EzSolver tại {_EZSOLVER_DIR} — git clone "
            "https://github.com/ismoiloffS/EzSolver"
        )
    env = dict(os.environ)
    env["MAX_WORKERS"] = str(_EZSOLVER_MAX_WORKERS)
    _ezsolver_proc = subprocess.Popen(
        [sys.executable, str(_EZSOLVER_SERVICE_FILE)],
        cwd=str(_EZSOLVER_DIR),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    # Đợi service lên (tối đa 20s)
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        try:
            import urllib.request

            with urllib.request.urlopen(f"{_EZSOLVER_HOST}/health", timeout=2):
                return
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    raise EventistaError("EzSolver service không lên sau 20s")


async def _ezsolver_solve(
    sitekey: str,
    siteurl: str,
    *,
    proxy: str | None = None,
    log: Callable[[str], None],
) -> str:
    """Solve Turnstile qua EzSolver local service → trả token.

    Truyền proxy của job (http://user:pass@host:port) để Chrome EzSolver dùng
    đúng IP như Camoufox — tránh token solve từ IP local bị site reject.
    """
    _ezsolver_ensure_service()
    log("[captcha] ezsolver: service OK, gửi solve request")
    payload = {"sitekey": sitekey, "siteurl": siteurl, "timeout": 90}
    if proxy:
        payload["proxy"] = proxy
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{_EZSOLVER_HOST}/solve",
            json=payload,
        )
        if resp.status_code != 200:
            raise EventistaError(
                f"EzSolver solve fail: HTTP {resp.status_code} — {resp.text[:300]}"
            )
        data = resp.json()
        token = (data.get("token") or "").strip()
        if not token:
            raise EventistaError(f"EzSolver trả về không có token: {data}")
        log(f"[captcha] ezsolver: solved trong {data.get('elapsed')}s")
        return token


async def _do_registration(
    page: Any,
    *,
    email: str,
    password: str,
    captcha_mode: str,
    yescaptcha_key: str | None,
    proxy: str | None = None,
    log: Callable[[str], None],
) -> None:
    """Thực hiện flow đăng ký trên trang. Raise EventistaError nếu fail."""
    log(f"● Mở trang đích {_SITE_URL}")
    await page.goto(_SITE_URL, wait_until="domcontentloaded", timeout=60000)

    # 1. Mở login dialog — site render 2 element btn-signin (desktop + mobile),
    # React render sau domcontentloaded → phải chờ selector rồi mới click element visible.
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
            raise EventistaError("btn-signin không tồn tại trên trang")
        await page.wait_for_selector("#login-form", state="visible", timeout=10000)
    except EventistaError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise EventistaError(
            f"không mở được dialog Đăng nhập ([data-id=btn-signin]): {exc}"
        ) from exc
    log("● Mở dialog Đăng nhập")

    # 2. Chuyển sang form đăng ký
    clicked = await _click_by_text(page, "Đăng ký ngay")
    if not clicked:
        raise EventistaError("không tìm thấy nút 'Đăng ký ngay' trong login dialog")
    await page.locator("#register-form").wait_for(state="visible", timeout=15000)
    log("● Mở form đăng ký")

    # 3. Điền email + password (human-like typing, kích hoạt React onChange).
    # Lưu ý: input[name=email|password] tồn tại ở CẢ login-form lẫn register-form →
    # phải scope theo #register-form, không dùng input[name=...] trần.
    await page.locator('#register-form input[name="email"]').press_sequentially(
        email, delay=random.randint(30, 70)
    )
    await page.locator('#register-form input[name="password"]').press_sequentially(
        password, delay=random.randint(30, 70)
    )
    await page.locator('#register-form input[name="confirmPassword"]').press_sequentially(
        password, delay=random.randint(30, 70)
    )
    log("● Điền form đăng ký")

    # 4. Đồng ý điều khoản
    try:
        await page.locator("#agree-terms").click(timeout=10000)
    except Exception as exc:  # noqa: BLE001
        raise EventistaError(f"không tick được #agree-terms: {exc}") from exc

    # 5. Captcha
    await _solve_turnstile(
        page, mode=captcha_mode, yescaptcha_key=yescaptcha_key, proxy=proxy, log=log
    )

    # 6. Submit
    try:
        submit = page.locator('button[type="submit"][form="register-form"]')
        await submit.click(timeout=15000)
    except Exception as exc:  # noqa: BLE001
        raise EventistaError(f"không bấm được nút đăng ký: {exc}") from exc
    log("● Gửi form đăng ký — chờ kết quả...")

    # 7. Chờ thành công / lỗi
    deadline = time.monotonic() + _REGISTER_WAIT_SECONDS
    while time.monotonic() < deadline:
        await asyncio.sleep(2.0)
        try:
            url = page.url
            if "verify-account" in url:
                log("✓ Đăng ký thành công — redirect verify-account")
                return
            body_text = await page.evaluate(
                "() => (document.body ? document.body.innerText : '') || ''"
            )
        except Exception:  # noqa: BLE001
            continue
        low = body_text.lower()
        if any(hint in low for hint in _SUCCESS_HINTS):
            log("✓ Đăng ký thành công (thông báo trên trang)")
            return
        for hint in _ERROR_HINTS:
            if hint in low and any(
                k in low for k in ("đăng ký", "email", "tài khoản", "mật khẩu")
            ):
                raise EventistaError(f"register bị chặn: {hint!r} — {body_text[:300]}")
    raise EventistaError(
        f"không xác nhận được kết quả register trong {int(_REGISTER_WAIT_SECONDS)}s"
    )


async def _open_activation_link(
    page: Any,
    url: str,
    *,
    log: Callable[[str], None],
) -> None:
    """Mở link kích hoạt; chờ redirect về site + text xác nhận."""
    log("● Mở link kích hoạt từ email")
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        await asyncio.sleep(1.5)
        try:
            body_text = await page.evaluate(
                "() => (document.body ? document.body.innerText : '') || ''"
            )
            low = body_text.lower()
        except Exception:  # noqa: BLE001
            continue
        if any(k in low for k in ("kích hoạt thành công", "verified", "active", "xác nhận thành công")):
            log("✓ Kích hoạt thành công")
            return
        if any(k in low for k in ("expired", "hết hạn", "invalid")):
            log("⚠ Link báo expired/invalid — vẫn coi là đã xử lý")
            return


async def _verify_login(
    page: Any,
    *,
    email: str,
    password: str,
    log: Callable[[str], None],
) -> None:
    """Đăng nhập lại bằng account vừa kích hoạt → xác nhận account hoạt động."""
    log("● Verify đăng nhập — mở trang")
    await page.goto(_SITE_URL, wait_until="domcontentloaded", timeout=60000)
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
        raise EventistaError("login verify: btn-signin không tồn tại")
    await page.locator("#login-form").wait_for(state="visible", timeout=10000)
    await page.locator('#login-form input[name="email"]').press_sequentially(
        email, delay=random.randint(30, 70)
    )
    await page.locator('#login-form input[name="password"]').press_sequentially(
        password, delay=random.randint(30, 70)
    )
    log("● Bấm Đăng nhập")
    await page.locator('[data-id="btn-login"]').click(timeout=15000)
    deadline = time.monotonic() + 20.0
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
        low = last_body.lower()
        if not dialog_visible:
            log("✓ Đăng nhập thành công — account hoạt động")
            return
        for hint in (
            "mật khẩu không đúng",
            "sai mật khẩu",
            "không tồn tại",
            "không chính xác",
            "email hoặc mật khẩu",
            "thất bại",
        ):
            if hint in low:
                raise EventistaError(
                    f"login verify fail: {hint!r} — {last_body[:300]}"
                )
    raise EventistaError(
        f"login verify: không xác nhận được kết quả sau 20s — {last_body[:300]}"
    )


# ── Mail polling ─────────────────────────────────────────────────────────


async def _find_activation_link(
    combo: OutlookCombo,
    *,
    proxy: str | None,
    log: Callable[[str], None],
) -> str | None:
    """Poll hòm thư tìm email kích hoạt → trả link verify-email (hoặc None).

    Fetch full body (không phải bodyPreview — link nằm sâu trong HTML).
    """
    kwargs: dict[str, Any] = {"timeout": 30.0}
    if proxy:
        kwargs["proxy"] = proxy

    async with httpx.AsyncClient(**kwargs) as client:
        access = await _refresh_access(client, combo)
        for _ in range(3):  # retry list fetch — Graph có thể rate-limit tạm thời
            resp = await client.get(
                "https://graph.microsoft.com/v1.0/me/messages",
                params={
                    "$top": 30,
                    "$orderby": "receivedDateTime desc",
                    "$select": "subject,from,receivedDateTime,body,isRead",
                },
                headers={"Authorization": f"Bearer {access}"},
            )
            if resp.status_code == 200:
                break
            await asyncio.sleep(2.0)
        else:
            raise EventistaError(
                f"Graph API không trả mail để tìm link kích hoạt: HTTP {resp.status_code}"
            )

        messages = resp.json().get("value", [])
        for msg in messages:
            subject = (msg.get("subject") or "").lower()
            if not any(k in subject for k in _ACTIVATION_SUBJECTS):
                continue
            body = msg.get("body") or {}
            content = (body.get("content") or "")
            if not content:
                content = msg.get("bodyPreview") or ""
            match = _ACTIVATION_URL_RE.search(content)
            if not match:
                continue
            link = match.group(0).replace("&amp;", "&")
            log(f"[mail] ✓ tìm thấy link kích hoạt ({msg.get('receivedDateTime', '')})")
            return link
    return None


# ── Manager ──────────────────────────────────────────────────────────────


class EventistaManager:
    """Quản lý Eventista jobs: queue + workers + SSE + DB persistence.

    In-memory (giống UpiJobManager) — không recover sau restart.
    Config hydrate từ Settings Store qua ``apply_settings`` (startup boot).
    """

    def __init__(self, *, max_concurrent: int = 1) -> None:
        self._max = max(1, min(30, int(max_concurrent)))
        self._job_timeout: float = 600.0
        self._engine: str = "camoufox"
        self._headless: bool = False
        self._default_password: str | None = None
        self._use_proxy: bool = True
        self._captcha_mode: str = "auto"
        self._poll_timeout_seconds: float = 600.0
        self._yescaptcha_key: str | None = None

        self.jobs: dict[str, EventistaJob] = {}
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
    def default_password(self) -> str | None:
        return self._default_password

    @property
    def use_proxy(self) -> bool:
        return self._use_proxy

    @property
    def captcha_mode(self) -> str:
        return self._captcha_mode

    @property
    def poll_timeout_seconds(self) -> float:
        return self._poll_timeout_seconds

    @property
    def yescaptcha_key(self) -> str | None:
        return self._yescaptcha_key

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

    def set_default_password(self, value: str | None) -> None:
        self._default_password = (value or "").strip() or None

    def set_use_proxy(self, value: bool) -> None:
        self._use_proxy = bool(value)

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

    def set_job_timeout(self, value: float) -> None:
        if not (30 <= value <= 3600):
            raise ValueError(f"job_timeout phải trong [30, 3600], nhận {value}")
        self._job_timeout = float(value)

    def set_yescaptcha_key(self, value: str | None) -> None:
        self._yescaptcha_key = (value or "").strip() or None

    def apply_settings(self, settings: dict) -> None:
        """Hydrate fields từ settings dict (startup boot). Best-effort — value
        sai bị bỏ qua, không raise để startup không gãy vì 1 key xấu."""
        if "eventista.max_concurrent" in settings:
            val = int(settings["eventista.max_concurrent"])
            if 1 <= val <= 30:
                self._max = val
        if "eventista.job_timeout" in settings:
            val = float(settings["eventista.job_timeout"])
            if 30 <= val <= 3600:
                self._job_timeout = val
        if "eventista.engine" in settings and settings["eventista.engine"] in (
            "camoufox", "playwright", "chrome", "cloakbrowser"
        ):
            self._engine = settings["eventista.engine"]
        if "eventista.headless" in settings:
            self._headless = bool(settings["eventista.headless"])
        if "eventista.default_password" in settings:
            self._default_password = (settings["eventista.default_password"] or "").strip() or None
        if "eventista.use_proxy" in settings:
            self._use_proxy = bool(settings["eventista.use_proxy"])
        if "eventista.captcha_mode" in settings and settings["eventista.captcha_mode"] in (
            "auto", "click", "yescaptcha", "ezsolver", "camoufox", "inpage", "none"
        ):
            self._captcha_mode = settings["eventista.captcha_mode"]
        if "eventista.poll_timeout_seconds" in settings:
            val = float(settings["eventista.poll_timeout_seconds"])
            if 30 <= val <= 3600:
                self._poll_timeout_seconds = val
        if "eventista.yescaptcha_key" in settings:
            self._yescaptcha_key = (settings["eventista.yescaptcha_key"] or "").strip() or None
        # Seed từ env (YESCAPTCHA_CLIENT_KEY) — chỉ khi DB chưa có value.
        elif _YESCAPTCHA_ENV_KEY and not self._yescaptcha_key:
            self._yescaptcha_key = _YESCAPTCHA_ENV_KEY

    def to_config_dict(self) -> dict[str, Any]:
        return {
            "max_concurrent": self._max,
            "job_timeout": self._job_timeout,
            "engine": self._engine,
            "headless": self._headless,
            "default_password": self._default_password or "",
            "use_proxy": self._use_proxy,
            "captcha_mode": self._captcha_mode,
            "poll_timeout_seconds": self._poll_timeout_seconds,
            "yescaptcha_key": self._yescaptcha_key or "",
        }

    # ── SSE broadcast ──────────────────────────────────────────────────

    def _broadcast(self, event: dict[str, Any]) -> None:
        from .manager import _sse_mux

        if _sse_mux is not None:
            _sse_mux.publish("eventista", event)

    def _broadcast_job(self, job: EventistaJob) -> None:
        self._broadcast({"type": "job", "job": job.to_dict()})

    def _job_log(self, job: EventistaJob, msg: str) -> None:
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

    def add_jobs(self, combos: list[str]) -> list[EventistaJob]:
        existing = {j.email.lower() for j in self.jobs.values() if j.status != "cancelled"}
        out: list[EventistaJob] = []
        for raw in combos:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            try:
                combo = OutlookCombo.parse(line)
            except OutlookComboError as exc:
                jid = uuid.uuid4().hex[:12]
                job = EventistaJob(
                    id=jid, email="<invalid>", password="",
                    status="error", error=str(exc), finished_at=time.time(),
                )
                self.jobs[jid] = job
                self.order.append(jid)
                self._broadcast_job(job)
                out.append(job)
                continue
            if combo.email.lower() in existing:
                jid = uuid.uuid4().hex[:12]
                job = EventistaJob(
                    id=jid, email=combo.email, password="",
                    status="error",
                    error="combo đã có trong danh sách (chưa kết thúc)",
                    finished_at=time.time(),
                )
                self.jobs[jid] = job
                self.order.append(jid)
                self._broadcast_job(job)
                out.append(job)
                continue
            existing.add(combo.email.lower())
            password = self._default_password or generate_password()
            jid = uuid.uuid4().hex[:12]
            job = EventistaJob(
                id=jid,
                email=combo.email,
                password=password,
                engine=self._engine,
                _refresh_token=combo.refresh_token,
                _client_id=combo.client_id,
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
        """Requeue 1 job (error/cancelled). True nếu requeue được."""
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
        """Xoá TẤT CẢ jobs (kể cả queued/running — running bị cancel)."""
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
        """Build Success/Error output lines (email|password|secret_2fa cho success).

        Chỉ gọi qua API authed — password nằm trong payload này.
        """
        success: list[str] = []
        errors: list[str] = []
        for jid in self.order:
            job = self.jobs.get(jid)
            if not job:
                continue
            if job.status == "success":
                success.append(f"{job.email}|{job.password}|no_2fa")
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

    async def _run_job(self, job: EventistaJob) -> None:
        job.status = "running"
        job.started_at = time.time()
        self._broadcast_job(job)
        self._job_log(job, "● Bắt đầu job")

        # Persist trạng thái registering
        try:
            self._persist(
                job, status="registering",
            )
        except Exception as exc:  # noqa: BLE001
            self._job_log(job, f"DB persist fail (best-effort): {exc}")

        # Resolve proxy
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
            self._persist(job, status="failed", error=job.error)
        except EventistaError as exc:
            job.error = _short_error(str(exc))
            job.status = "error"
            self._job_log(job, f"✗ {job.error}")
            self._persist(job, status="failed", error=job.error)
        except Exception as exc:  # noqa: BLE001
            # Lỗi browser/network — thử phân loại + xử lý proxy chết
            await self._handle_browser_failure(job, exc)
            job.error = _short_error(f"{type(exc).__name__}: {exc}")
            job.status = "error"
            self._job_log(job, f"✗ {job.error}")
            self._persist(job, status="failed", error=job.error)
        finally:
            job.finished_at = time.time()
            self._broadcast_job(job)

    async def _handle_browser_failure(self, job: EventistaJob, exc: Exception) -> None:
        """Xử lý lỗi browser launch/goto — mark proxy chết nếu là lỗi network.

        Reuse ``is_network_error`` + ``get_proxy_pool().mark_dead`` (cùng cơ chế
        với Reg/UPI): proxy connection refused → loại khỏi pool để job sau
        không dính lại proxy chết.
        """
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

    async def _run_job_inner(self, job: EventistaJob, *, proxy: str | None) -> None:
        # Khởi tạo combo từ token đã lưu (cần refresh_token để poll mail).
        if not job._refresh_token or not job._client_id:
            raise EventistaError(
                "combo thiếu refresh_token/client_id — không poll mail activation được"
            )
        combo = OutlookCombo(
            email=job.email,
            password=job.password,
            refresh_token=job._refresh_token,
            client_id=job._client_id,
        )

        engine = _resolve_browser_engine(
            self._engine,
            log=lambda m: self._job_log(job, m),
        )
        job.engine = engine

        # ── Phase 1: đăng ký browser ──
        page, _handle, close = await _launch_browser(
            engine,
            headless=self._headless,
            proxy=proxy,
            camoufox_captcha=(engine == "camoufox" and self._captcha_mode == "camoufox"),
        )
        try:
            await _do_registration(
                page,
                email=job.email,
                password=job.password,
                captcha_mode=self._captcha_mode,
                yescaptcha_key=self._yescaptcha_key,
                proxy=proxy,
                log=lambda m: self._job_log(job, m),
            )
        finally:
            try:
                await close()
            except Exception as exc:  # noqa: BLE001
                self._job_log(job, f"close browser: {exc}")
        self._persist(job, status="registered")

        # ── Phase 2: poll mail tìm link kích hoạt ──
        self._job_log(
            job, f"● Đợi email kích hoạt — poll tối đa {int(self._poll_timeout_seconds)}s"
        )
        activation_url: str | None = None
        deadline = time.monotonic() + self._poll_timeout_seconds
        last_err: str | None = None
        while time.monotonic() < deadline:
            try:
                activation_url = await _find_activation_link(
                    combo, proxy=proxy, log=lambda m: self._job_log(job, m)
                )
                if activation_url:
                    break
            except OutlookComboError as exc:
                last_err = str(exc)
                self._job_log(job, f"✗ [mail] combo dead: {last_err}")
                break
            except EventistaError as exc:
                last_err = str(exc)
                self._job_log(job, f"✗ [mail] {last_err}")
                break
            except Exception as exc:  # noqa: BLE001
                last_err = f"{type(exc).__name__}: {exc}"
                self._job_log(job, f"● [mail] lỗi tạm thời — retry: {last_err}")
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)

        if not activation_url:
            raise EventistaError(
                last_err or f"không tìm thấy email kích hoạt trong {int(self._poll_timeout_seconds)}s"
            )
        job.activation_url = activation_url
        job.mail_found_at = time.time()
        self._persist(job, status="registered", activation_url=activation_url)

        # ── Phase 3: mở link kích hoạt ──
        page2, _handle2, close2 = await _launch_browser(
            engine, headless=self._headless, proxy=proxy
        )
        try:
            await _open_activation_link(
                page2, activation_url, log=lambda m: self._job_log(job, m)
            )
        finally:
            try:
                await close2()
            except Exception as exc:  # noqa: BLE001
                self._job_log(job, f"close browser: {exc}")

        # ── Phase 4: login verify — đăng nhập lại kiểm tra account hoạt động ──
        page3, _handle3, close3 = await _launch_browser(
            engine, headless=self._headless, proxy=proxy
        )
        try:
            await _verify_login(
                page3,
                email=job.email,
                password=job.password,
                log=lambda m: self._job_log(job, m),
            )
        finally:
            try:
                await close3()
            except Exception as exc:  # noqa: BLE001
                self._job_log(job, f"close browser: {exc}")

        job.activated_at = time.time()
        job.status = "success"
        job.error = None
        self._job_log(job, "✓ activated + login OK — tag combo Eventista")
        # Tag combo + persist DB
        try:
            self._mark_used(job.email)
        except Exception as exc:  # noqa: BLE001
            self._job_log(job, f"DB tag fail (best-effort): {exc}")
        self._persist(job, status="activated", activation_url=activation_url)

    # ── DB persistence ─────────────────────────────────────────────────

    def _eventista_repo(self):
        from db import get_engine, get_eventista_repo

        return get_eventista_repo(get_engine())

    def _combo_repo(self):
        from db import get_engine, get_combo_repo

        return get_combo_repo(get_engine())

    def _persist(
        self,
        job: EventistaJob,
        *,
        status: str,
        error: str | None = None,
        activation_url: str | None = None,
    ) -> None:
        try:
            self._eventista_repo().upsert(
                job.email,
                job.password,
                status=status,
                error=error,
                activation_url=activation_url,
                engine=job.engine,
                proxy_used=job._proxy_used,
            )
        except Exception as exc:  # noqa: BLE001
            self._job_log(job, f"DB persist fail (best-effort): {exc}")

    def _mark_used(self, email: str) -> None:
        self._combo_repo().mark_eventista_used(email)


# Singleton
_eventista_manager: EventistaManager | None = None


def get_eventista_manager() -> EventistaManager:
    global _eventista_manager  # noqa: PLW0603
    if _eventista_manager is None:
        _eventista_manager = EventistaManager(max_concurrent=1)
    return _eventista_manager
