import pytest
from playwright.sync_api import Error as PlaywrightError

from bhka.v1 import search_session as search_session_module
from bhka.v1.contracts import NetworkBudget, QuerySpec
from bhka.v1.pipeline import PlatformCircuitBreak
from bhka.v1.search_session import (
    BilibiliSearchPageDiscoverer,
    ManagedEdgeSearchSession,
    SearchPageSnapshot,
    SearchSessionError,
)


class FakeSession:
    def __init__(self, status_code=200):
        self.status_code = status_code
        self.queries = []

    def search(self, query):
        self.queries.append(query)
        return SearchPageSnapshot(
            html=(
                '<a href="https://www.bilibili.com/video/BV1AbCdEf123" '
                'title="PCB 教程">PCB 教程</a>'
            ),
            status_code=self.status_code,
            final_url="https://search.bilibili.com/all",
        )


def test_discoverer_converts_one_page_to_candidates():
    session = FakeSession()
    discoverer = BilibiliSearchPageDiscoverer(session)

    candidates = discoverer.discover(
        QuerySpec(text="STM32 PCB", purpose="precise"),
        budget=NetworkBudget(),
    )

    assert session.queries == ["STM32 PCB"]
    assert [candidate.canonical_id for candidate in candidates] == ["BV1AbCdEf123"]


def test_discoverer_maps_http_412_to_run_wide_circuit_signal():
    discoverer = BilibiliSearchPageDiscoverer(FakeSession(status_code=412))

    with pytest.raises(PlatformCircuitBreak) as error:
        discoverer.discover(
            QuerySpec(text="STM32 PCB", purpose="precise"),
            budget=NetworkBudget(),
        )

    assert error.value.code == "http_412"


def test_managed_session_requires_context_and_rejects_bad_settings(tmp_path):
    with pytest.raises(ValueError):
        ManagedEdgeSearchSession(tmp_path, timeout_seconds=1)
    with pytest.raises(ValueError):
        ManagedEdgeSearchSession(tmp_path, scroll_rounds=6)

    session = ManagedEdgeSearchSession(tmp_path)
    with pytest.raises(SearchSessionError):
        session.search("test")


def test_managed_search_falls_back_when_persistent_profile_is_locked(tmp_path, monkeypatch):
    contexts = []

    class FakeContext:
        def close(self):
            return None

    class FakeChromium:
        def launch_persistent_context(self, profile, **_kwargs):
            contexts.append(profile)
            if len(contexts) == 1:
                raise PlaywrightError("profile is in use")
            return FakeContext()

    class FakePlaywright:
        chromium = FakeChromium()

        def stop(self):
            return None

    class FakeStarter:
        def start(self):
            return FakePlaywright()

    monkeypatch.setattr(search_session_module, "sync_playwright", lambda: FakeStarter())

    with ManagedEdgeSearchSession(tmp_path) as session:
        assert session.using_ephemeral_profile
        assert len(contexts) == 2
        assert contexts[0] == str(tmp_path.resolve())
