from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import bhka.browser_login as login_module
from bhka.browser_login import interactive_edge_login, render_netscape_cookies
from bhka.config import Settings
from bhka.models import AuthenticationStatus


def make_settings(root: Path) -> Settings:
    return Settings(
        project_root=root,
        openai_api_key=None,
        openai_model="test",
        deepseek_api_key=None,
        deepseek_model="test",
        deepseek_base_url="https://example.invalid",
        cookies_file=None,
        cookies_from_browser=None,
        bilibili_user_agent=None,
        timeout_seconds=5,
        retries=0,
        rate_limit_seconds=0,
    )


def sample_cookies() -> list[dict]:
    return [
        {
            "domain": ".bilibili.com",
            "path": "/",
            "secure": True,
            "expires": 1_900_000_000,
            "httpOnly": True,
            "name": "SESSDATA",
            "value": "bilibili-secret",
        },
        {
            "domain": ".example.com",
            "path": "/",
            "secure": True,
            "expires": 1_900_000_000,
            "httpOnly": False,
            "name": "session",
            "value": "unrelated-secret",
        },
    ]


def test_netscape_export_contains_only_bilibili_domains():
    output = render_netscape_cookies(sample_cookies())

    assert "#HttpOnly_.bilibili.com" in output
    assert "bilibili-secret" in output
    assert "example.com" not in output
    assert "unrelated-secret" not in output


def test_managed_login_writes_local_cookie_and_updates_configuration(tmp_path, monkeypatch):
    class FakeResponse:
        ok = True

        @staticmethod
        def json():
            return {"code": 0, "data": {"isLogin": True}}

    class FakeRequest:
        @staticmethod
        def get(url, timeout):
            return FakeResponse()

    class FakePage:
        @staticmethod
        def goto(url, wait_until, timeout):
            return None

        @staticmethod
        def evaluate(expression):
            return "Mozilla/5.0 managed-edge-test"

    class FakeContext:
        def __init__(self):
            self.pages = [FakePage()]
            self.request = FakeRequest()

        @staticmethod
        def cookies(urls):
            return sample_cookies()

        @staticmethod
        def close():
            return None

    class FakeChromium:
        @staticmethod
        def launch_persistent_context(profile, **kwargs):
            return FakeContext()

    class FakePlaywright:
        chromium = FakeChromium()

    @contextmanager
    def fake_sync_playwright():
        yield FakePlaywright()

    class FakeSource:
        def __init__(self, settings):
            self.settings = settings

        @staticmethod
        def verify_auth():
            return AuthenticationStatus(configured=True, is_login=True, status="valid")

    auth_dir = tmp_path / "local-auth"
    (tmp_path / ".env").write_text("DEEPSEEK_API_KEY=keep-secret\n", encoding="utf-8")
    monkeypatch.setattr(login_module, "sync_playwright", fake_sync_playwright)
    monkeypatch.setattr(login_module, "default_auth_dir", lambda root: auth_dir)
    monkeypatch.setattr(login_module, "restrict_cookie_file", lambda path: None)
    monkeypatch.setattr(login_module, "YtDlpDataSource", FakeSource)

    progress: list[str] = []
    result = interactive_edge_login(make_settings(tmp_path), progress=progress.append)

    cookie_text = result.cookie_file.read_text(encoding="utf-8")
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert result.cookie_count == 1
    assert "bilibili-secret" in cookie_text
    assert "unrelated-secret" not in cookie_text
    assert "BILIBILI_COOKIES_FROM_BROWSER=" in env_text
    assert "BILIBILI_USER_AGENT=Mozilla/5.0 managed-edge-test" in env_text
    assert "DEEPSEEK_API_KEY=keep-secret" in env_text
    assert all("bilibili-secret" not in message for message in progress)
