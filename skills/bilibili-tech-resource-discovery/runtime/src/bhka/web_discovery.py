from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote_plus, urlparse
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


class PublicIndexError(RuntimeError):
    """Failure from the built-in, keyless public search-index fallback."""


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
TextTransport = Callable[[Request, int], str]


class PublicIndexClient:
    """Small no-key public-index client used when Firecrawl is not configured."""

    def __init__(
        self,
        *,
        base_url: str = "https://html.duckduckgo.com/html/",
        github_base_url: str = "https://api.github.com/search/repositories",
        timeout_seconds: int = 15,
        transport: TextTransport | None = None,
    ):
        self.base_url = base_url
        self.github_base_url = github_base_url
        self.timeout_seconds = timeout_seconds
        self._transport = transport or _default_text_transport

    def search(self, query: str, *, limit: int = 8) -> list[FirecrawlSearchHit]:
        normalized = " ".join(query.split())
        if not normalized:
            raise ValueError("Public-index search query cannot be empty")
        if not 1 <= limit <= 20:
            raise ValueError("Public-index search limit must be between 1 and 20")
        if normalized.lower().startswith("site:github.com "):
            return self._search_github(normalized[16:], limit=limit)
        request = Request(
            f"{self.base_url}?q={quote_plus(normalized)}",
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
                ),
            },
        )
        try:
            payload = self._transport(request, self.timeout_seconds)
        except HTTPError as exc:
            raise PublicIndexError(f"Public index returned HTTP {exc.code}.") from exc
        except (TimeoutError, URLError) as exc:
            raise PublicIndexError("Public index could not be reached.") from exc
        except (UnicodeDecodeError, ValueError) as exc:
            raise PublicIndexError("Public index returned an invalid response.") from exc
        lowered = payload.lower()
        if "anomaly-modal" in lowered or "challenge-form" in lowered:
            raise PublicIndexError("Public index temporarily requested human verification.")
        return _parse_public_index_payload(payload, limit=limit)

    def _search_github(self, query: str, *, limit: int) -> list[FirecrawlSearchHit]:
        query = re.sub(
            r"\b(open[ -]?source|source code)\b",
            " ",
            query,
            flags=re.IGNORECASE,
        )
        query = re.sub(r"(?:开源代码|开源资料|项目资料|开源|源码)", " ", query)
        query = " ".join(query.split())
        hits = self._request_github(query, limit=limit)
        ascii_query = " ".join(
            token for token in query.split() if re.search(r"[A-Za-z0-9]", token)
        )
        if not hits and ascii_query and ascii_query != query:
            hits = self._request_github(ascii_query, limit=limit)
        return hits

    def _request_github(self, query: str, *, limit: int) -> list[FirecrawlSearchHit]:
        request = Request(
            f"{self.github_base_url}?q={quote_plus(query)}&per_page={limit}",
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "bhka-public-index/0.8",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            payload = json.loads(self._transport(request, self.timeout_seconds))
        except HTTPError as exc:
            raise PublicIndexError(f"GitHub public search returned HTTP {exc.code}.") from exc
        except (TimeoutError, URLError) as exc:
            raise PublicIndexError("GitHub public search could not be reached.") from exc
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError) as exc:
            raise PublicIndexError("GitHub public search returned an invalid response.") from exc
        rows = payload.get("items", []) if isinstance(payload, dict) else []
        return [
            FirecrawlSearchHit(
                url=str(item.get("html_url") or ""),
                title=str(item.get("full_name") or ""),
                description=str(item.get("description") or ""),
            )
            for item in rows[:limit]
            if isinstance(item, dict) and _is_http_url(str(item.get("html_url") or ""))
        ]


class _DuckDuckGoResultParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results: list[tuple[str, str]] = []
        self._href: str | None = None
        self._title: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "a" and "result__a" in (values.get("class") or "").split():
            self._href = values.get("href")
            self._title = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._title.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href:
            self.results.append((self._href, " ".join(self._title).strip()))
            self._href = None
            self._title = []


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


def learning_search_focus(requirement: str) -> str:
    """Remove request phrasing while preserving the user's actual learning topic."""
    cleaned = " ".join(requirement.split())
    patterns = (
        r"我(?:想|希望|要)(?:学习|了解|看)?(?:一下)?",
        r"请(?:帮我)?",
        r"帮我",
        r"我该(?:看|学)?",
        r"应该(?:看|学)?",
        r"推荐(?:一些|几个)?",
        r"有(?:哪些|什么)",
        r"哪些",
    )
    for pattern in patterns:
        cleaned = re.sub(pattern, " ", cleaned)
    cleaned = re.sub(r"[，。！？、,;；?]+", " ", cleaned)
    cleaned = " ".join(cleaned.split()).strip()
    return " ".join(extract_query_anchors(cleaned)) or cleaned or requirement


def build_firecrawl_queries(requirement: str, mode: str = "resources") -> list[str]:
    topic = " ".join(requirement.split())
    if not topic:
        raise ValueError("Requirement cannot be empty")
    if mode == "learning":
        focus = learning_search_focus(topic)
        return [
            f"site:bilibili.com/video {focus} 教程",
            f"site:bilibili.com/video {focus} 从零 全流程",
            f"site:bilibili.com/video {focus} 实战 案例",
            f"site:bilibili.com/video {focus} 系列课程",
            f"site:bilibili.com/video {focus} 经验 复盘",
        ]
    if mode != "resources":
        raise ValueError("mode must be learning or resources")
    focus = " ".join(extract_query_anchors(topic)) or topic
    return [
        f"site:github.com {focus} 开源代码",
        f"site:gitee.com {focus} 源码",
        f"site:oshwhub.com {focus} 立创开源",
        f"site:bilibili.com/video {focus} 开源 项目资料",
        f"site:bilibili.com/video {focus} 教程 实战 方案",
    ]


def discover_with_firecrawl(
    client: FirecrawlClient,
    requirement: str,
    *,
    per_query: int = 8,
    mode: str = "resources",
    progress: Callable[[str], None] | None = None,
) -> PublicWebDiscovery:
    discovery = PublicWebDiscovery(queries=build_firecrawl_queries(requirement, mode=mode))
    first_error: FirecrawlError | None = None
    for index, query in enumerate(discovery.queries, 1):
        if progress:
            progress(f"Public-web search {index}/{len(discovery.queries)}")
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


def discover_with_public_index(
    client: PublicIndexClient,
    requirement: str,
    *,
    per_query: int = 8,
    mode: str = "resources",
    progress: Callable[[str], None] | None = None,
) -> PublicWebDiscovery:
    """Discover candidates without an API key using ordinary indexed pages."""
    discovery = PublicWebDiscovery(queries=build_firecrawl_queries(requirement, mode=mode))
    for index, query in enumerate(discovery.queries, 1):
        if progress:
            progress(f"Public-index search {index}/{len(discovery.queries)}")
        try:
            hits = client.search(query, limit=per_query)
        except PublicIndexError:
            discovery.failures.append("public_index")
            continue
        discovery.result_count += len(hits)
        for hit in hits:
            _collect_url(hit.url, discovery)
            for url in URL_RE.findall(f"{hit.description}\n{hit.markdown}"):
                _collect_url(url.rstrip(".,;:!?"), discovery)
    if not discovery.result_count and discovery.failures:
        raise PublicIndexError("Public-index discovery was unavailable.")
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


def _parse_public_index_payload(payload: str, *, limit: int) -> list[FirecrawlSearchHit]:
    """Accept DuckDuckGo HTML and RSS fixtures/providers without brittle regex parsing."""
    hits: list[FirecrawlSearchHit] = []
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        parser = _DuckDuckGoResultParser()
        parser.feed(payload)
        rows = [(url, title, "") for url, title in parser.results]
    else:
        rows = [
            (
                (item.findtext("link") or "").strip(),
                (item.findtext("title") or "").strip(),
                (item.findtext("description") or "").strip(),
            )
            for item in root.findall(".//item")
        ]
    for raw_url, title, description in rows:
        url = _unwrap_public_index_url(raw_url)
        if not _is_http_url(url):
            continue
        hits.append(FirecrawlSearchHit(url=url, title=title, description=description))
        if len(hits) >= limit:
            break
    return hits


def _unwrap_public_index_url(url: str) -> str:
    if url.startswith("//"):
        url = f"https:{url}"
    try:
        parsed = urlparse(url)
        if parsed.hostname in {"duckduckgo.com", "www.duckduckgo.com"}:
            target = parse_qs(parsed.query).get("uddg", [])
            if target:
                return target[0]
    except ValueError:
        return ""
    return url


def _default_transport(request: Request, timeout_seconds: int) -> dict[str, Any]:
    with urlopen(request, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def _default_text_transport(request: Request, timeout_seconds: int) -> str:
    with urlopen(request, timeout=timeout_seconds) as response:
        return response.read().decode("utf-8", errors="replace")
