from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import uuid4

from playwright.sync_api import Error as PlaywrightError

from bhka.browser_login import (
    BrowserLoginError,
    context_is_logged_in,
    is_bilibili_cookie,
    render_netscape_cookies,
    restrict_cookie_file,
    update_env,
)
from bhka.config import Settings
from bhka.source import DataSourceError, YtDlpDataSource

from .search_session import ManagedEdgeSearchSession

LOGIN_URL = "https://passport.bilibili.com/login"


@dataclass(frozen=True)
class V1LoginResult:
    cookie_file: Path
    cookie_count: int


def _write_private_cookie_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def interactive_v1_login(
    settings: Settings,
    *,
    timeout_seconds: int = 300,
    progress: Callable[[str], None] | None = None,
) -> V1LoginResult:
    """Log in once using the same private Edge profile later used for search pages."""

    if not 60 <= timeout_seconds <= 900:
        raise ValueError("Login timeout must be between 60 and 900 seconds")
    report = progress or (lambda _message: None)
    auth_dir = settings.project_root / ".auth"
    profile_dir = auth_dir / "v1-edge-profile"
    cookies: list[dict[str, object]] = []
    user_agent = ""
    report("正在打开项目专属 Edge 窗口，请在窗口内正常登录 B 站。")
    report("登录信息只保存在本机，不会显示、上传或写入报告。")
    try:
        with ManagedEdgeSearchSession(
            profile_dir,
            visible=True,
            allow_ephemeral_fallback=False,
        ) as session:
            context = session.context
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30_000)
            user_agent = page.evaluate("navigator.userAgent")
            deadline = time.monotonic() + timeout_seconds
            while time.monotonic() < deadline:
                if context_is_logged_in(context):
                    cookies = context.cookies(
                        ["https://www.bilibili.com", "https://api.bilibili.com"]
                    )
                    break
                time.sleep(1)
    except PlaywrightError as exc:
        raise BrowserLoginError("项目专属 Edge 登录窗口无法正常使用。") from exc
    if not cookies:
        raise BrowserLoginError("未在限定时间内检测到 B 站登录，或登录窗口已关闭。")
    filtered = [cookie for cookie in cookies if is_bilibili_cookie(cookie)]
    if not filtered:
        raise BrowserLoginError("登录成功，但没有获得 B 站域名的本地会话信息。")
    cookie_file = auth_dir / "bilibili.cookies.txt"
    _write_private_cookie_file(cookie_file, render_netscape_cookies(filtered))
    restrict_cookie_file(cookie_file)
    update_env(
        settings.project_root / ".env",
        {
            "BILIBILI_COOKIES_FILE": cookie_file.as_posix(),
            "BILIBILI_COOKIES_FROM_BROWSER": "",
            "BILIBILI_USER_AGENT": user_agent,
        },
    )
    verification_settings = replace(
        settings,
        cookies_file=cookie_file,
        cookies_from_browser=None,
        bilibili_user_agent=user_agent,
    )
    try:
        auth = YtDlpDataSource(verification_settings).verify_auth()
    except DataSourceError as exc:
        raise BrowserLoginError("登录信息已安全保存，但 B 站验证失败。") from exc
    if auth.status != "valid":
        raise BrowserLoginError("登录信息已保存，但 B 站返回未登录状态。")
    report("B 站登录已验证，后续搜索将复用这个项目专属会话。")
    return V1LoginResult(cookie_file=cookie_file, cookie_count=len(filtered))
