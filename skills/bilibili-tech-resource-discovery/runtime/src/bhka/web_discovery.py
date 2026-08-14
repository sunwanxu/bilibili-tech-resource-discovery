from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .discovery import extract_query_anchors

FIRECRAWL_SEARCH_PATH = "/v2/search"
URL_RE = re.compile(r"https?://[^\s<>\"'\\)\]}，。；]+", re.IGNORECASE)
BILIBILI_VIDEO_RE = re.compile(
    r"https?://(?:www\.)?bilibili\.com/video/(?:BV[0-9A-Za-z]+|(?:av)?\d+)",
    re.IGNORECASE,
)
RESOURCE_HOSTS = {
    "github.com",
    "www.github.com",
    "gitee.com",
    "www.gitee.com",
    "gitcode.com",
    "www.gitcode.com",
    "gitcode.net",
    "codeberg.org",
    "oshwhub.com",
    "www.oshwhub.com",
}
RESERVED_RESOURCE_ROOTS = {
    "about",
    "actions",
    "activities",
    "article",
    "contact",
    "education",
    "explore",
    "features",
    "help",
    "login",
    "market",
    "marketplace",
    "orgs",
    "organizations",
    "project",
    "recommend",
    "settings",
    "sign_in",
    "signup",
    "sponsors",
    "topics",
}
MAX_DISCOVERED_VIDEOS = 50
MAX_DISCOVERED_RESOURCES = 50


class FirecrawlError(RuntimeError):
    def __init__(self, message: str, *, category: str, retryable: bool = False):
        super().__init__(message)
        self.category = category
        self.retryable = retryable


@dataclass(frozen=True)
class FirecrawlSearchHit:
    url: str
    title: str = ""
    description: str = ""
    markdown: str = ""


@dataclass
class PublicWebDiscovery:
    video_urls: list[str] = field(default_factory=list)
    resource_urls: list[str] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    result_count: int = 0
    failures: list[str] = field(default_factory=list)


JsonTransport = Callable[[Request, int], dict[str, Any]]


class FirecrawlClient:
    """Small Firecrawl v2 client that keeps the provider optional."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.firecrawl.dev",
        timeout_seconds: int = 20,
        transport: JsonTransport | None = None,
    ):
        if not api_key.strip():
            raise FirecrawlError(
                "Firecrawl is not configured.",
                category="configuration",
            )
        self._api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._transport = transport or _default_transport

    def search(self, query: str, *, limit: int = 5) -> list[FirecrawlSearchHit]:
        normalized = " ".join(query.split())
        if not normalized:
            raise ValueError("Firecrawl search query cannot be empty")
        if not 1 <= limit <= 10:
            raise ValueError("Firecrawl search limit must be between 1 and 10")

        # Keep the broad discovery pass shallow. Selected project/video pages
        # are inspected later by the evidence pipeline instead of scraping
        # every search result up front.
        payload = json.dumps({"query": normalized, "limit": limit}).encode("utf-8")
        request = Request(
            f"{self.base_url}{FIRECRAWL_SEARCH_PATH}",
            data=payload,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "User-Agent": "bhka-firecrawl/0.1",
            },
            method="POST",
        )
        try:
            response = self._transport(request, self.timeout_seconds)
        except HTTPError as exc:
            if exc.code in {401, 403}:
                category = "authentication"
                retryable = False
            elif exc.code == 429:
                category = "rate_limited"
                retryable = True
            elif 500 <= exc.code < 600:
                category = "upstream"
                retryable = True
            else:
                category = "http_error"
                retryable = False
            raise FirecrawlError(
                f"Firecrawl request failed with HTTP {exc.code}.",
                category=category,
                retryable=retryable,
            ) from exc
        except (TimeoutError, URLError) as exc:
            raise FirecrawlError(
                "Firecrawl could not be reached.",
                category="network",
                retryable=True,
            ) from exc
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError) as exc:
            raise FirecrawlError(
                "Firecrawl returned an invalid response.",
                category="invalid_response",
            ) from exc

        if response.get("success") is False:
            raise FirecrawlError(
                "Firecrawl reported an unsuccessful search.",
                category="upstream",
                retryable=True,
            )
        rows = _search_rows(response)
        hits: list[FirecrawlSearchHit] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            url = str(row.get("url") or "").strip()
            if not _is_http_url(url):
                continue
            hits.append(
                FirecrawlSearchHit(
                    url=url,
                    title=str(row.get("title") or ""),
                    description=str(row.get("description") or ""),
                    markdown=str(row.get("markdown") or ""),
                )
            )
        return hits


def build_firecrawl_queries(requirement: str) -> list[str]:
    topic = " ".join(requirement.split())
    if not topic:
        raise ValueError("Requirement cannot be empty")
    focus = " ".join(extract_query_anchors(topic)) or topic
    return [
        f"{focus} 开源代码 GitHub",
        f"{focus} 源码 Gitee",
        f"{focus} 立创开源 OSHWHub",
        f"site:bilibili.com/video {focus} 开源 项目资料",
        f"site:bilibili.com/video {focus} 教程 实战 方案",
    ]


def discover_with_firecrawl(
    client: FirecrawlClient,
    requirement: str,
    *,
    per_query: int = 8,
) -> PublicWebDiscovery:
    discovery = PublicWebDiscovery(queries=build_firecrawl_queries(requirement))
    first_error: FirecrawlError | None = None
    for query in discovery.queries:
        try:
            hits = client.search(query, limit=per_query)
        except FirecrawlError as exc:
            first_error = first_error or exc
            discovery.failures.append(exc.category)
            continue
        discovery.result_count += len(hits)
        for hit in hits:
            _collect_url(hit.url, discovery)
            for url in URL_RE.findall(f"{hit.description}\n{hit.markdown}"):
                _collect_url(url.rstrip(".,;:!?"), discovery)
    if not discovery.result_count and first_error:
        raise first_error
    return discovery


def _collect_url(url: str, discovery: PublicWebDiscovery) -> None:
    video = BILIBILI_VIDEO_RE.match(url)
    if video:
        _append_unique(
            discovery.video_urls,
            video.group(0),
            limit=MAX_DISCOVERED_VIDEOS,
        )
        return
    resource = _canonical_resource_url(url)
    if resource:
        _append_unique(
            discovery.resource_urls,
            resource,
            limit=MAX_DISCOVERED_RESOURCES,
        )


def _canonical_resource_url(url: str) -> str | None:
    try:
        parsed = urlparse(url)
        _ = parsed.hostname
    except ValueError:
        return None
    host = parsed.netloc.lower()
    if host not in RESOURCE_HOSTS:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2 or parts[0].lower() in RESERVED_RESOURCE_ROOTS:
        return None
    owner, project = parts[:2]
    if project.lower() in {"activity", "followers", "following", "stars"}:
        return None
    return f"https://{host.removeprefix('www.')}/{owner}/{project.removesuffix('.git')}"


def _append_unique(values: list[str], value: str, *, limit: int) -> None:
    if value not in values and len(values) < limit:
        values.append(value)


def _is_http_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        _ = parsed.hostname
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except ValueError:
        return False


def _search_rows(response: dict[str, Any]) -> list[Any]:
    data = response.get("data", [])
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        web = data.get("web", [])
        return web if isinstance(web, list) else []
    return []


def _default_transport(request: Request, timeout_seconds: int) -> dict[str, Any]:
    with urlopen(request, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))
