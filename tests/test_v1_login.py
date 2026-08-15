from types import SimpleNamespace

from bhka.config import Settings
from bhka.v1 import login as login_module


def settings(tmp_path):
    return Settings(
        project_root=tmp_path,
        openai_api_key=None,
        openai_model="unused",
        deepseek_api_key=None,
        deepseek_model="unused",
        deepseek_base_url="https://example.invalid",
        cookies_file=None,
        cookies_from_browser=None,
        bilibili_user_agent=None,
        timeout_seconds=20,
        retries=1,
        rate_limit_seconds=0,
    )


class FakePage:
    def goto(self, *_args, **_kwargs):
        return None

    def evaluate(self, _expression):
        return "test-user-agent"


class FakeContext:
    def __init__(self):
        self.pages = [FakePage()]

    def cookies(self, _urls):
        return [
            {
                "domain": ".bilibili.com",
                "path": "/",
                "secure": True,
                "httpOnly": True,
                "expires": 0,
                "name": "SESSDATA",
                "value": "local-secret",
            }
        ]


class FakeSession:
    def __init__(self, profile_dir, *, visible):
        self.profile_dir = profile_dir
        self.visible = visible
        self.context = FakeContext()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


def test_v1_login_reuses_search_profile_and_exports_bilibili_only_cookie(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(login_module, "ManagedEdgeSearchSession", FakeSession)
    monkeypatch.setattr(login_module, "context_is_logged_in", lambda _context: True)
    monkeypatch.setattr(login_module, "restrict_cookie_file", lambda _path: None)
    monkeypatch.setattr(
        login_module,
        "YtDlpDataSource",
        lambda _settings: SimpleNamespace(
            verify_auth=lambda: SimpleNamespace(status="valid")
        ),
    )

    result = login_module.interactive_v1_login(settings(tmp_path), timeout_seconds=60)

    assert result.cookie_count == 1
    assert result.cookie_file == tmp_path / ".auth" / "bilibili.cookies.txt"
    assert "local-secret" in result.cookie_file.read_text(encoding="utf-8")
    env = (tmp_path / ".env").read_text(encoding="utf-8")
    assert result.cookie_file.as_posix() in env
    assert "local-secret" not in env
