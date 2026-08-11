from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlencode

from yt_dlp import YoutubeDL
from yt_dlp.cookies import CookieLoadError
from yt_dlp.networking.exceptions import RequestError
from yt_dlp.utils import DownloadError

from .config import Settings
from .models import (
    AuthenticationStatus,
    Comment,
    PartSelection,
    RawVideoData,
    SearchResult,
    SubtitleTrack,
    VideoMetadata,
    VideoPart,
)

BVID_RE = re.compile(r"(?i)(BV[0-9A-Za-z]{10})")
AV_URL_RE = re.compile(
    r"(?i)(?:https?://(?:www\.)?bilibili\.com/video/)?(?:av)?(\d+)(?:[/?#].*)?"
)
SUPPORTED_COOKIE_BROWSERS = {
    "brave",
    "chrome",
    "chromium",
    "edge",
    "firefox",
    "opera",
    "safari",
    "vivaldi",
    "whale",
}


class DataSourceError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        category: str = "upstream",
        deterministic: bool = False,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.deterministic = deterministic

    @property
    def retryable(self) -> bool:
        return not self.deterministic and self.category != "rate_limited"


def classify_failure(message: str) -> tuple[str, bool, str]:
    """Return category, determinism, and a safe explanation for an upstream failure."""
    lowered = message.lower()
    if "http error 412" in lowered or "precondition failed" in lowered:
        return (
            "rate_limited",
            True,
            "Bilibili returned HTTP 412 risk control; remaining Bilibili requests were stopped.",
        )
    if "could not copy" in lowered and "cookie" in lowered:
        return (
            "authentication",
            True,
            "The browser cookie database could not be copied, usually because it is locked.",
        )
    if "dpapi" in lowered or "decrypt" in lowered and "cookie" in lowered:
        return (
            "authentication",
            True,
            "Windows could not decrypt this browser's cookies in the current application context.",
        )
    if any(
        marker in lowered
        for marker in (
            "browser profile",
            "could not find chrome cookies database",
            "could not find firefox cookies database",
            "unsupported browser",
            "cookie file does not exist",
        )
    ):
        return "authentication", True, "The configured browser profile or cookie file is unavailable."
    return "upstream", False, message


class VideoDataSource(Protocol):
    def fetch(
        self,
        video: str,
        include_comments: bool = False,
        part: int | None = None,
    ) -> RawVideoData: ...


def normalize_bvid(value: str) -> str:
    match = BVID_RE.search(value.strip())
    if not match:
        raise ValueError("Expected a Bilibili BV id or a URL containing one")
    return "BV" + match.group(1)[2:]


def normalize_video_id(value: str) -> str:
    """Return a canonical BV id or an ``av<aid>`` id from an id or video URL."""
    stripped = value.strip()
    bvid = BVID_RE.search(stripped)
    if bvid:
        return "BV" + bvid.group(1)[2:]
    av = AV_URL_RE.fullmatch(stripped)
    if av:
        return f"av{av.group(1)}"
    raise ValueError("Expected a Bilibili BV/AV id, numeric aid, or video URL")


def browser_cookie_spec(value: str) -> tuple[str, ...]:
    browser, separator, profile = value.strip().partition(":")
    browser = browser.lower()
    if browser not in SUPPORTED_COOKIE_BROWSERS:
        supported = ", ".join(sorted(SUPPORTED_COOKIE_BROWSERS))
        raise ValueError(f"Unsupported cookie browser {browser!r}; choose one of: {supported}")
    if separator and not profile.strip():
        raise ValueError("Browser cookie profile cannot be empty after ':'")
    return (browser, profile.strip(), None, None) if separator else (browser,)


class _CaptureLogger:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def debug(self, message: str) -> None:
        pass

    def info(self, message: str) -> None:
        pass

    def warning(self, message: str) -> None:
        self.warnings.append(message)

    def error(self, message: str) -> None:
        self.warnings.append(message)


class YtDlpDataSource:
    """Thin, replaceable adapter around the actively maintained yt-dlp extractor."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def verify_auth(self) -> AuthenticationStatus:
        """Check Bilibili's account-status endpoint without exposing account identity."""
        configured = bool(self.settings.cookies_file or self.settings.cookies_from_browser)
        if not configured:
            return AuthenticationStatus(configured=False, is_login=None, status="unconfigured")
        options: dict[str, Any] = {
            "quiet": True,
            "skip_download": True,
            "socket_timeout": self.settings.timeout_seconds,
            "retries": 0,
            "logger": _CaptureLogger(),
        }
        self._apply_cookie_options(options)
        try:
            with YoutubeDL(options) as ydl:
                payload = self._read_json(
                    ydl,
                    "https://api.bilibili.com/x/web-interface/nav",
                )
        except (CookieLoadError, DownloadError, RequestError, OSError, ValueError) as exc:
            raise self._friendly_error("Bilibili login verification failed", exc) from exc
        data = payload.get("data") or {}
        is_login = bool(data.get("isLogin"))
        if payload.get("code") not in {0, -101}:
            raise DataSourceError(
                "Bilibili login verification returned an unexpected API response.",
                category="upstream",
            )
        return AuthenticationStatus(
            configured=True,
            is_login=is_login,
            status="valid" if is_login else "invalid",
        )

    def _friendly_error(self, context: str, exc: Exception) -> DataSourceError:
        category, deterministic, safe_reason = classify_failure(str(exc))
        browser = self.settings.cookies_from_browser
        browser_context = f" Configured browser: {browser_cookie_spec(browser)[0]}." if browser else ""
        return DataSourceError(
            f"{context}.{browser_context} {safe_reason}".strip(),
            category=category,
            deterministic=deterministic,
        )

    def fetch(
        self,
        video: str,
        include_comments: bool = False,
        part: int | None = None,
    ) -> RawVideoData:
        if part is not None and part < 1:
            raise ValueError("Part number must be at least 1")
        video_id = normalize_video_id(video)
        bvid = video_id if video_id.startswith("BV") else ""
        url = f"https://www.bilibili.com/video/{video_id}"
        if part is not None:
            url = f"{url}?p={part}"
        logger = _CaptureLogger()
        options: dict[str, Any] = {
            "quiet": True,
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "allsubtitles": True,
            "ignore_no_formats_error": True,
            "noplaylist": True,
            "socket_timeout": self.settings.timeout_seconds,
            "retries": self.settings.retries,
            "sleep_interval_requests": self.settings.rate_limit_seconds,
            # yt-dlp's Bilibili extractor walks every comment page before it
            # returns. Phase 1 only needs a bounded sample, fetched below.
            "getcomments": False,
            "logger": logger,
        }
        self._apply_cookie_options(options)
        try:
            with YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=False)
                if not info:
                    raise DataSourceError(f"yt-dlp returned no information for {video}")
                info = self._first_entry(info)
                bvid = normalize_video_id(
                    " ".join(str(info.get(key) or "") for key in ("id", "display_id", "webpage_url"))
                )
                resolved_url = f"https://www.bilibili.com/video/{bvid}"
                if part is not None:
                    resolved_url = f"{resolved_url}?p={part}"
                comments = (
                    self._bounded_comments(ydl, bvid, limit=20, logger=logger)
                    if include_comments
                    else []
                )
        except (CookieLoadError, DownloadError) as exc:
            raise self._friendly_error(f"yt-dlp could not fetch {bvid}", exc) from exc
        return RawVideoData(
            fetched_at=datetime.now(UTC),
            source="yt-dlp",
            metadata=self._metadata(bvid, resolved_url, info, part),
            subtitles=self._subtitles(info),
            comments=comments,
            warnings=logger.warnings,
        )

    def search(self, query: str, limit: int = 20) -> list[SearchResult]:
        """Use yt-dlp's maintained Bilibili search extractor without resolving videos."""
        if not query.strip():
            raise ValueError("Search query cannot be empty")
        if not 1 <= limit <= 50:
            raise ValueError("Search limit must be between 1 and 50")
        logger = _CaptureLogger()
        options: dict[str, Any] = {
            "quiet": True,
            "skip_download": True,
            "extract_flat": "in_playlist",
            "playlistend": limit,
            "socket_timeout": self.settings.timeout_seconds,
            "retries": self.settings.retries,
            "sleep_interval_requests": self.settings.rate_limit_seconds,
            "logger": logger,
        }
        self._apply_cookie_options(options)
        try:
            with YoutubeDL(options) as ydl:
                info = ydl.extract_info(f"bilisearch{limit}:{query.strip()}", download=False)
        except (CookieLoadError, DownloadError) as exc:
            raise self._friendly_error(f"Bilibili search failed for {query!r}", exc) from exc
        entries = (info or {}).get("entries") or []
        results = []
        for rank, item in enumerate((entry for entry in entries if entry), 1):
            raw_id = str(item.get("id") or "")
            raw_url = str(item.get("url") or item.get("webpage_url") or "")
            try:
                source_id = normalize_video_id(raw_url or raw_id)
            except ValueError:
                try:
                    source_id = normalize_video_id(raw_id)
                except ValueError:
                    continue
            if source_id:
                results.append(SearchResult(
                    source_id=source_id,
                    webpage_url=f"https://www.bilibili.com/video/{source_id}",
                    query=query.strip(),
                    rank=rank,
                ))
        return results

    def preview(self, video: str) -> VideoMetadata:
        """Read lightweight public metadata for shortlist ranking without format extraction."""
        video_id = normalize_video_id(video)
        query = urlencode(
            {"bvid": video_id} if video_id.startswith("BV") else {"aid": video_id[2:]}
        )
        options: dict[str, Any] = {
            "quiet": True,
            "skip_download": True,
            "socket_timeout": self.settings.timeout_seconds,
            "retries": self.settings.retries,
        }
        self._apply_cookie_options(options)
        try:
            with YoutubeDL(options) as ydl:
                payload = self._read_json(
                    ydl,
                    f"https://api.bilibili.com/x/web-interface/view?{query}",
                )
        except (CookieLoadError, RequestError, OSError, ValueError) as exc:
            raise self._friendly_error(f"Could not preview {video}", exc) from exc
        data = payload.get("data") or {}
        if payload.get("code") != 0 or not data.get("bvid"):
            raise DataSourceError(f"Bilibili view API did not resolve {video}")
        timestamp = data.get("pubdate")
        published = datetime.fromtimestamp(timestamp, UTC) if timestamp else None
        stats = data.get("stat") or {}
        bvid = data["bvid"]
        return VideoMetadata(
            bvid=bvid,
            title=data.get("title") or bvid,
            description=data.get("desc") or "",
            author=(data.get("owner") or {}).get("name"),
            publish_time=published,
            views=stats.get("view"),
            likes=stats.get("like"),
            favorites=stats.get("favorite"),
            coins=stats.get("coin"),
            comments_count=stats.get("reply"),
            duration_seconds=data.get("duration"),
            webpage_url=f"https://www.bilibili.com/video/{bvid}",
        )

    def list_parts(self, video: str) -> list[VideoPart]:
        """Read the complete part directory with one bounded API request."""
        video_id = normalize_video_id(video)
        options: dict[str, Any] = {
            "quiet": True,
            "skip_download": True,
            "socket_timeout": self.settings.timeout_seconds,
            "retries": self.settings.retries,
        }
        self._apply_cookie_options(options)
        try:
            with YoutubeDL(options) as ydl:
                query = urlencode(
                    {"bvid": video_id}
                    if video_id.startswith("BV")
                    else {"aid": video_id[2:]}
                )
                payload = self._read_json(
                    ydl,
                    f"https://api.bilibili.com/x/web-interface/view?{query}",
                )
        except (CookieLoadError, RequestError, OSError, ValueError) as exc:
            raise self._friendly_error(f"Could not list parts for {video_id}", exc) from exc
        if payload.get("code") != 0:
            raise DataSourceError(
                f"Bilibili view API returned code {payload.get('code')} for {video_id}"
            )
        data = payload.get("data") or {}
        bvid = data.get("bvid") or video_id
        pages = data.get("pages") or []
        return [
            VideoPart(
                bvid=bvid,
                page=item["page"],
                cid=item["cid"],
                title=item.get("part") or f"P{item['page']}",
                duration_seconds=item.get("duration"),
                webpage_url=f"https://www.bilibili.com/video/{bvid}?p={item['page']}",
            )
            for item in pages
        ]

    def _apply_cookie_options(self, options: dict[str, Any]) -> None:
        if self.settings.bilibili_user_agent:
            headers = dict(options.get("http_headers") or {})
            headers["User-Agent"] = self.settings.bilibili_user_agent
            options["http_headers"] = headers
        if self.settings.cookies_file:
            self._validate_cookie_file(self.settings.cookies_file)
            options["cookiefile"] = str(self.settings.cookies_file)
        if self.settings.cookies_from_browser:
            if self.settings.cookies_file:
                raise DataSourceError(
                    "Configure only one of BILIBILI_COOKIES_FILE and "
                    "BILIBILI_COOKIES_FROM_BROWSER",
                    category="authentication",
                    deterministic=True,
                )
            try:
                options["cookiesfrombrowser"] = browser_cookie_spec(
                    self.settings.cookies_from_browser
                )
            except ValueError as exc:
                raise DataSourceError(
                    str(exc),
                    category="authentication",
                    deterministic=True,
                ) from exc

    @staticmethod
    def _validate_cookie_file(path: Path) -> None:
        if not path.is_file():
            raise DataSourceError(
                f"Cookie file does not exist: {path}",
                category="authentication",
                deterministic=True,
            )

    @staticmethod
    def _first_entry(info: dict[str, Any]) -> dict[str, Any]:
        entries = info.get("entries")
        if entries:
            first = next((item for item in entries if item), None)
            if first:
                return first
        return info

    @staticmethod
    def _metadata(
        bvid: str,
        url: str,
        info: dict[str, Any],
        part: int | None = None,
    ) -> VideoMetadata:
        timestamp = info.get("timestamp")
        published = datetime.fromtimestamp(timestamp, UTC) if timestamp else None
        return VideoMetadata(
            bvid=bvid,
            title=info.get("title") or bvid,
            description=info.get("description") or "",
            author=info.get("uploader"),
            publish_time=published,
            views=info.get("view_count"),
            likes=info.get("like_count"),
            favorites=None,
            coins=None,
            comments_count=info.get("comment_count"),
            tags=list(info.get("tags") or []),
            duration_seconds=info.get("duration"),
            webpage_url=url,
            part_number=part,
            part_title=info.get("title") if part is not None else None,
        )

    @staticmethod
    def _subtitles(info: dict[str, Any]) -> list[SubtitleTrack]:
        tracks: list[SubtitleTrack] = []
        for language, variants in (info.get("subtitles") or {}).items():
            if language == "danmaku":
                continue
            texts = [v.get("data") for v in variants or [] if v.get("data")]
            if texts:
                tracks.append(SubtitleTrack(language=language, text="\n".join(texts)))
        return tracks

    @staticmethod
    def _comments(info: dict[str, Any], limit: int) -> list[Comment]:
        result = []
        for item in (info.get("comments") or [])[:limit]:
            timestamp = item.get("timestamp")
            result.append(Comment(
                author=item.get("author"),
                text=item.get("text") or "",
                likes=item.get("like_count"),
                published_at=datetime.fromtimestamp(timestamp, UTC) if timestamp else None,
            ))
        return result

    @classmethod
    def _bounded_comments(
        cls,
        ydl: YoutubeDL,
        bvid: str,
        limit: int,
        logger: _CaptureLogger,
    ) -> list[Comment]:
        """Fetch one bounded Bilibili comment page using yt-dlp's cookie session."""
        try:
            view_query = urlencode({"bvid": bvid})
            view = cls._read_json(
                ydl,
                f"https://api.bilibili.com/x/web-interface/view?{view_query}",
            )
            aid = (view.get("data") or {}).get("aid")
            if view.get("code") != 0 or not aid:
                logger.warning(f"Bilibili view API did not return an aid for {bvid}")
                return []

            reply_query = urlencode({
                "pn": 1,
                "ps": limit,
                "oid": aid,
                "type": 1,
                "sort": 2,
            })
            payload = cls._read_json(
                ydl,
                f"https://api.bilibili.com/x/v2/reply?{reply_query}",
            )
            if payload.get("code") != 0:
                logger.warning(
                    f"Bilibili reply API returned code {payload.get('code')} for {bvid}"
                )
                return []
            return cls._parse_bilibili_comments(payload, limit)
        except (RequestError, OSError, ValueError) as exc:
            category, deterministic, safe_reason = classify_failure(str(exc))
            if category == "rate_limited":
                raise DataSourceError(
                    safe_reason,
                    category=category,
                    deterministic=deterministic,
                ) from exc
            logger.warning(f"Bounded comment fetch failed for {bvid}: {type(exc).__name__}")
            return []

    @staticmethod
    def _read_json(ydl: YoutubeDL, url: str) -> dict[str, Any]:
        with ydl.urlopen(url) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _parse_bilibili_comments(payload: dict[str, Any], limit: int) -> list[Comment]:
        result: list[Comment] = []

        def append_reply(reply: dict[str, Any]) -> None:
            if len(result) >= limit:
                return
            timestamp = reply.get("ctime")
            result.append(Comment(
                author=((reply.get("member") or {}).get("uname")),
                text=((reply.get("content") or {}).get("message") or ""),
                likes=reply.get("like"),
                published_at=(
                    datetime.fromtimestamp(timestamp, UTC) if timestamp else None
                ),
            ))
            for child in reply.get("replies") or []:
                append_reply(child)

        for reply in ((payload.get("data") or {}).get("replies") or []):
            append_reply(reply)
            if len(result) >= limit:
                break
        return result


FOUNDATION_TERMS = (
    "基本信息",
    "内部结构",
    "最小系统",
    "系统架构",
    "存储器结构",
    "时钟源",
    "时钟树",
)
PERIPHERAL_TERMS = (
    "gpio",
    "串口",
    "uart",
    "usart",
    "i2c",
    "spi",
    "dma",
    "定时器",
    "adc",
    "中断",
)
PRACTICAL_TERMS = ("实验", "项目", "实战", "综合", "制作", "作品", "调试")


def select_representative_parts(
    parts: list[VideoPart],
    limit: int = 4,
) -> list[PartSelection]:
    """Select a small, deterministic semantic sample from a multipart video."""
    if limit < 1:
        raise ValueError("Sample size must be at least 1")
    if not parts:
        return []

    selected: list[PartSelection] = []
    used: set[int] = set()

    def add(part: VideoPart, role: str, reason: str) -> None:
        if len(selected) < limit and part.page not in used:
            selected.append(PartSelection(role=role, reason=reason, part=part))
            used.add(part.page)

    add(parts[0], "introduction", "首个分 P，用于识别课程定位和前置要求")

    foundation = next(
        (part for part in parts[1:] if _contains_any(part.title, FOUNDATION_TERMS)),
        None,
    )
    if foundation:
        add(foundation, "foundation", "标题命中基础结构或系统原理信号")

    peripheral_candidates = [
        part for part in parts if _contains_any(part.title, PERIPHERAL_TERMS)
    ]
    if peripheral_candidates:
        midpoint = (parts[0].page + parts[-1].page) / 2
        peripheral = min(
            peripheral_candidates,
            key=lambda item: (abs(item.page - midpoint), item.page),
        )
        add(peripheral, "peripheral", "靠近课程中段的外设或通信章节")

    practical = next(
        (part for part in reversed(parts) if _contains_any(part.title, PRACTICAL_TERMS)),
        None,
    )
    if practical:
        add(practical, "practical", "靠后的实验、项目或调试章节")

    if len(selected) < min(limit, len(parts)):
        if limit == 1:
            positions = [0]
        else:
            positions = [round(i * (len(parts) - 1) / (limit - 1)) for i in range(limit)]
        for position in positions:
            add(parts[position], "coverage", "语义角色不足时补充的均匀覆盖样本")
    for part in parts:
        add(part, "coverage", "补足指定样本数量")
    return selected


def _contains_any(value: str, terms: tuple[str, ...]) -> bool:
    lowered = value.lower()
    return any(term in lowered for term in terms)
