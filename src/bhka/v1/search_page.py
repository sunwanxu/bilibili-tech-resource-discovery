from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from .contracts import DiscoveryCandidate

_VIDEO_ID_RE = re.compile(r"(?i)(BV[0-9A-Za-z]{10}|av\d+)(?=$|[/?#])")
_NUMERIC_VIDEO_PATH_RE = re.compile(r"(?i)/video/(\d+)(?=$|[/?#])")


def canonical_video_id(value: str) -> str | None:
    """Normalize identifiers emitted by Bilibili result pages without network access."""

    try:
        parsed = urlparse(value)
    except ValueError:
        return None
    path = parsed.path if parsed.scheme or parsed.netloc else value
    match = _VIDEO_ID_RE.search(path)
    if match:
        identifier = match.group(1)
        if identifier.lower().startswith("av"):
            return f"av{identifier[2:]}"
        return f"BV{identifier[2:]}"
    numeric = _NUMERIC_VIDEO_PATH_RE.search(path)
    if numeric:
        return f"av{numeric.group(1)}"
    return None


class _VideoAnchorParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.anchor_active = False
        self.active_href = ""
        self.active_title = ""
        self.active_text: list[str] = []
        self.items: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "a" or self.anchor_active:
            return
        values = {key.casefold(): value or "" for key, value in attrs}
        href = values.get("href", "")
        if canonical_video_id(href) is None:
            return
        self.anchor_active = True
        self.active_href = href
        self.active_title = values.get("title", "") or values.get("aria-label", "")
        self.active_text = []

    def handle_data(self, data: str) -> None:
        if self.anchor_active:
            self.active_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "a" and self.anchor_active:
            text = " ".join("".join(self.active_text).split())
            title = " ".join((self.active_title or text).split())
            self.items.append((self.active_href, title))
            self.anchor_active = False
            self.active_href = ""
            self.active_title = ""
            self.active_text = []


class SearchPageCandidateParser:
    """Convert one user-visible Bilibili search page into normalized candidates."""

    def parse(self, html: str, *, query: str) -> list[DiscoveryCandidate]:
        parser = _VideoAnchorParser()
        parser.feed(html)
        candidates: dict[str, DiscoveryCandidate] = {}
        for href, title in parser.items:
            canonical_id = canonical_video_id(href)
            if canonical_id is None:
                continue
            key = canonical_id.casefold()
            normalized_url = urljoin("https://www.bilibili.com", href)
            normalized_url = normalized_url.split("?", 1)[0].split("#", 1)[0]
            if key not in candidates:
                candidates[key] = DiscoveryCandidate(
                    canonical_id=canonical_id,
                    url=normalized_url,
                    title=title,
                    provenance=["bilibili_search_page"],
                    matched_queries=[query],
                )
            elif not candidates[key].title and title:
                candidates[key].title = title
        return list(candidates.values())
