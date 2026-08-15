from __future__ import annotations

import re
from collections.abc import Iterable
from urllib.parse import urlparse, urlunparse

from .contracts import EvidenceRecord, ResourceKind, ResourceOrigin, ResourceRecord

_URL_RE = re.compile(r"https?://[^\s<>\"'）)】\]}，。；;]+", re.IGNORECASE)
_TRAILING_PUNCTUATION = ".,!?;:，。！？；："
_REPOSITORY_HOSTS = {"github.com", "gitee.com", "gitcode.com", "gitcode.net", "codeberg.org"}
_PCB_HOSTS = {"oshwhub.com", "oshwhub.com.cn"}
_SHARED_FILE_HOSTS = {
    "pan.baidu.com",
    "drive.google.com",
    "cloud.189.cn",
    "aliyundrive.com",
    "123pan.com",
    "cowtransfer.com",
    "wws.lanzouj.com",
    "lanzoux.com",
}
_COMMUNITY_HOSTS = {"qm.qq.com", "jq.qq.com", "discord.gg", "t.me"}
_DOCUMENT_SUFFIXES = {".pdf", ".doc", ".docx", ".md", ".txt", ".zip", ".7z", ".rar"}


def _normalized_host(value: str) -> str:
    host = value.casefold().split(":", 1)[0]
    return host.removeprefix("www.")


def normalize_resource_url(value: str) -> str | None:
    cleaned = value.strip().rstrip(_TRAILING_PUNCTUATION)
    try:
        parsed = urlparse(cleaned)
    except ValueError:
        return None
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        return None
    host = _normalized_host(parsed.hostname)
    if host.endswith("bilibili.com") or host == "b23.tv":
        return None
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urlunparse(("https", host, path, "", parsed.query, ""))


def repository_root(value: str) -> str | None:
    parsed = urlparse(value)
    host = _normalized_host(parsed.hostname or "")
    if host not in _REPOSITORY_HOSTS:
        return None
    segments = [segment for segment in parsed.path.split("/") if segment]
    if len(segments) < 2:
        return None
    owner, name = segments[:2]
    name = name.removesuffix(".git")
    if not owner or not name:
        return None
    return f"https://{host}/{owner}/{name}"


def classify_resource(value: str) -> ResourceKind:
    parsed = urlparse(value)
    host = _normalized_host(parsed.hostname or "")
    suffix = "." + parsed.path.rsplit(".", 1)[-1].casefold() if "." in parsed.path else ""
    if repository_root(value):
        return ResourceKind.REPOSITORY
    if host in _PCB_HOSTS or host.endswith(".oshwhub.com"):
        return ResourceKind.PCB_PROJECT
    if host in _SHARED_FILE_HOSTS or any(host.endswith(f".{item}") for item in _SHARED_FILE_HOSTS):
        return ResourceKind.SHARED_FILE
    if host in _COMMUNITY_HOSTS:
        return ResourceKind.COMMUNITY
    if suffix in _DOCUMENT_SUFFIXES:
        return ResourceKind.DOCUMENT
    return ResourceKind.UNKNOWN


def _context(text: str, start: int, end: int, *, radius: int = 90) -> str:
    return " ".join(text[max(0, start - radius) : min(len(text), end + radius)].split())


def extract_resource_records(evidence: Iterable[EvidenceRecord]) -> list[ResourceRecord]:
    resources: dict[str, ResourceRecord] = {}
    for record in evidence:
        text = record.text or ""
        for match in _URL_RE.finditer(text):
            normalized = normalize_resource_url(match.group(0))
            if normalized is None:
                continue
            root = repository_root(normalized)
            dedupe_key = (root or normalized).casefold()
            origin = ResourceOrigin(
                evidence_id=record.evidence_id,
                source_kind=record.source_kind,
                source_url=record.source_url,
                context=_context(text, match.start(), match.end()),
            )
            if dedupe_key not in resources:
                resources[dedupe_key] = ResourceRecord(
                    locator=normalized,
                    repository_root=root,
                    host=_normalized_host(urlparse(normalized).hostname or ""),
                    kind=classify_resource(normalized),
                    origins=[origin],
                )
                continue
            current = resources[dedupe_key]
            if all(item.evidence_id != origin.evidence_id for item in current.origins):
                current.origins.append(origin)
    return list(resources.values())


class EvidenceResourceExtractor:
    def extract(self, evidence: Iterable[EvidenceRecord]) -> list[ResourceRecord]:
        return extract_resource_records(evidence)
