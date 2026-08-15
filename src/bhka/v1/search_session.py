from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Self
from urllib.parse import urlencode

from playwright.sync_api import BrowserContext, Playwright, sync_playwright
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .contracts import DiscoveryCandidate, NetworkBudget, QuerySpec
from .pipeline import DiscoveryFailure, PlatformCircuitBreak
from .search_page import SearchPageCandidateParser

SEARCH_URL = "https://search.bilibili.com/all"


class SearchSessionError(RuntimeError):
    """A bounded browser/session failure safe to expose as a structured runtime error."""


@dataclass(frozen=True)
class SearchPageSnapshot:
    html: str
    status_code: int | None
    final_url: str


class SearchPageSession(Protocol):
    def search(self, query: str) -> SearchPageSnapshot: ...


class ManagedEdgeSearchSession:
    """A project-owned Edge profile that never reads the user's daily browser profile."""

    def __init__(
        self,
        profile_dir: Path,
        *,
        visible: bool = True,
        timeout_seconds: int = 30,
        scroll_rounds: int = 2,
    ):
        if timeout_seconds < 5:
            raise ValueError("timeout_seconds must be at least 5")
        if not 0 <= scroll_rounds <= 5:
            raise ValueError("scroll_rounds must be between 0 and 5")
        self.profile_dir = profile_dir.resolve()
        self.visible = visible
        self.timeout_ms = timeout_seconds * 1000
        self.scroll_rounds = scroll_rounds
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None

    def __enter__(self) -> Self:
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._playwright = sync_playwright().start()
            self._context = self._playwright.chromium.launch_persistent_context(
                str(self.profile_dir),
                channel="msedge",
                headless=not self.visible,
                viewport={"width": 1280, "height": 900},
                locale="zh-CN",
            )
        except PlaywrightError as exc:
            self.close()
            raise SearchSessionError(
                "The project-owned Microsoft Edge session could not be started."
            ) from exc
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        if self._context is not None:
            try:
                self._context.close()
            except PlaywrightError:
                pass
            self._context = None
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except PlaywrightError:
                pass
            self._playwright = None

    def search(self, query: str) -> SearchPageSnapshot:
        normalized = " ".join(query.split())
        if not normalized:
            raise ValueError("Search query cannot be empty")
        if self._context is None:
            raise SearchSessionError("ManagedEdgeSearchSession must be opened before use")
        url = f"{SEARCH_URL}?{urlencode({'keyword': normalized})}"
        page = self._context.pages[0] if self._context.pages else self._context.new_page()
        response = None
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            page.locator('a[href*="/video/"]').first.wait_for(
                state="attached",
                timeout=self.timeout_ms,
            )
            for _ in range(self.scroll_rounds):
                page.mouse.wheel(0, 1600)
                page.wait_for_timeout(500)
            return SearchPageSnapshot(
                html=page.content(),
                status_code=response.status if response is not None else None,
                final_url=page.url,
            )
        except PlaywrightTimeoutError as exc:
            status = response.status if response is not None else None
            if status == 412:
                raise PlatformCircuitBreak("http_412", "Bilibili search returned HTTP 412") from exc
            raise SearchSessionError(
                "Bilibili search page did not expose video results before the timeout."
            ) from exc
        except PlaywrightError as exc:
            raise SearchSessionError("Bilibili search page could not be read safely.") from exc
        finally:
            if len(self._context.pages) > 1:
                try:
                    page.close()
                except PlaywrightError:
                    pass


class BilibiliSearchPageDiscoverer:
    def __init__(
        self,
        session: SearchPageSession,
        *,
        parser: SearchPageCandidateParser | None = None,
    ):
        self.session = session
        self.parser = parser or SearchPageCandidateParser()

    def discover(
        self,
        query: QuerySpec,
        *,
        budget: NetworkBudget,
    ) -> list[DiscoveryCandidate]:
        try:
            snapshot = self.session.search(query.text)
        except SearchSessionError as exc:
            raise DiscoveryFailure("browser_search_failed", str(exc)) from exc
        if snapshot.status_code == 412:
            raise PlatformCircuitBreak("http_412", "Bilibili search returned HTTP 412")
        return self.parser.parse(snapshot.html, query=query.text)
