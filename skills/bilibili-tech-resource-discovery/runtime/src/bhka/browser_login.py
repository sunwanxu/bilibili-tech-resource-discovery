from __future__ import annotations

import os
import stat
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid4

from playwright.sync_api import BrowserContext, sync_playwright
from playwright.sync_api import Error as PlaywrightError

from .config import Settings
from .source import DataSourceError, YtDlpDataSource

LOGIN_URL = "https://passport.bilibili.com/login"
NAV_URL = "https://api.bilibili.com/x/web-interface/nav"


class BrowserLoginError(RuntimeError):
    pass


@dataclass(frozen=True)
class BrowserLoginResult:
    cookie_file: Path
    cookie_count: int


def default_auth_dir(project_root: Path) -> Path:
    return project_root / ".auth"


def is_bilibili_cookie(cookie: dict[str, Any]) -> bool:
    domain = str(cookie.get("domain") or "").lstrip(".").lower()
    return domain == "bilibili.com" or domain.endswith(".bilibili.com")


def render_netscape_cookies(cookies: list[dict[str, Any]]) -> str:
    lines = ["# Netscape HTTP Cookie File", "# Generated locally by bhka; treat as a password."]
    for cookie in sorted(cookies, key=lambda item: (str(item.get("domain")), str(item.get("name")))):
        if not is_bilibili_cookie(cookie):
            continue
        domain = str(cookie.get("domain") or "")
        output_domain = f"#HttpOnly_{domain}" if cookie.get("httpOnly") else domain
        include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
        secure = "TRUE" if cookie.get("secure") else "FALSE"
        expires_value = float(cookie.get("expires") or 0)
        expires = str(max(0, int(expires_value)))
        lines.append(
            "\t".join(
                (
                    output_domain,
                    include_subdomains,
                    str(cookie.get("path") or "/"),
                    secure,
                    expires,
                    str(cookie.get("name") or ""),
                    str(cookie.get("value") or ""),
                )
            )
        )
    return "\n".join(lines) + "\n"


def update_env(path: Path, updates: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8-sig").splitlines() if path.is_file() else []
    remaining = dict(updates)
    output: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in remaining:
                output.append(f"{key}={remaining.pop(key)}")
                continue
        output.append(line)
    if remaining and output and output[-1] != "":
        output.append("")
    output.extend(f"{key}={value}" for key, value in remaining.items())
    _atomic_write(path, "\n".join(output).rstrip() + "\n")


def _atomic_write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(value, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def restrict_cookie_file(path: Path) -> None:
    if os.name != "nt":
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        return
    identity = subprocess.run(
        ["whoami"],
        capture_output=True,
        check=False,
        text=True,
        timeout=5,
    ).stdout.strip()
    if not identity:
        raise BrowserLoginError("Could not identify the current Windows user for cookie-file ACLs.")
    result = subprocess.run(
        ["icacls", str(path), "/inheritance:r", "/grant:r", f"{identity}:(F)"],
        capture_output=True,
        check=False,
        text=True,
        timeout=10,
    )
    if result.returncode:
        path.unlink(missing_ok=True)
        raise BrowserLoginError("Could not restrict the local cookie file to the current user.")


def context_is_logged_in(context: BrowserContext) -> bool:
    response = context.request.get(NAV_URL, timeout=10_000)
    if not response.ok:
        return False
    payload = response.json()
    return bool((payload.get("data") or {}).get("isLogin"))


def interactive_edge_login(
    settings: Settings,
    *,
    timeout_seconds: int = 300,
    progress: Callable[[str], None] | None = None,
) -> BrowserLoginResult:
    """Open an isolated Edge login and persist only Bilibili-domain cookies locally."""
    if not 60 <= timeout_seconds <= 900:
        raise ValueError("Login timeout must be between 60 and 900 seconds")
    report = progress or (lambda _: None)
    cookies: list[dict[str, Any]] = []
    user_agent = ""
    report("Opening a dedicated Microsoft Edge window for Bilibili login...")
    report("Log in normally. Credentials remain in the browser and are never read by bhka.")
    try:
        with (
            TemporaryDirectory(prefix="bhka-edge-login-") as profile,
            sync_playwright() as playwright,
        ):
            context = playwright.chromium.launch_persistent_context(
                profile,
                channel="msedge",
                headless=False,
                viewport={"width": 1180, "height": 820},
            )
            try:
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
                if not cookies:
                    raise BrowserLoginError(
                        "Bilibili login was not detected before timeout or the window was closed."
                    )
            finally:
                try:
                    context.close()
                except PlaywrightError:
                    pass
    except BrowserLoginError:
        raise
    except PlaywrightError as exc:
        raise BrowserLoginError(
            "Microsoft Edge could not be started for isolated login."
        ) from exc

    filtered = [cookie for cookie in cookies if is_bilibili_cookie(cookie)]
    if not filtered:
        raise BrowserLoginError("Login succeeded, but no Bilibili-domain cookies were available.")
    auth_dir = default_auth_dir(settings.project_root)
    cookie_file = auth_dir / "bilibili.cookies.txt"
    _atomic_write(cookie_file, render_netscape_cookies(filtered))
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
        raise BrowserLoginError("Login cookies were saved, but verification failed safely.") from exc
    if auth.status != "valid":
        raise BrowserLoginError("Login cookies were saved, but Bilibili reports isLogin: false.")
    report("Bilibili login detected and verified. The dedicated Edge window can close.")
    return BrowserLoginResult(cookie_file=cookie_file, cookie_count=len(filtered))
