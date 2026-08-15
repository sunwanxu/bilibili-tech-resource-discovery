from __future__ import annotations

import hashlib
from typing import Protocol

from bhka.models import RawVideoData
from bhka.source import DataSourceError

from .contracts import (
    DiscoveryCandidate,
    EvidenceRecord,
    NetworkBudget,
    RetentionPolicy,
)
from .pipeline import CandidateReadError, PlatformCircuitBreak


class BoundedVideoSource(Protocol):
    def fetch(
        self,
        video: str,
        include_comments: bool = False,
        part: int | None = None,
    ) -> RawVideoData: ...


def _evidence_id(subject_id: str, source_kind: str, position: str) -> str:
    value = f"{subject_id}\n{source_kind}\n{position}".encode()
    return hashlib.sha256(value).hexdigest()[:24]


def _retained_text(value: str, retention: RetentionPolicy, *, limit: int) -> str:
    normalized = value.strip()
    if retention == RetentionPolicy.FULL_EVIDENCE:
        return normalized
    return normalized[:limit]


class YtDlpEvidenceReader:
    """Convert bounded yt-dlp output into the v1 evidence contract."""

    def __init__(self, source: BoundedVideoSource):
        self.source = source

    def read(
        self,
        candidate: DiscoveryCandidate,
        *,
        budget: NetworkBudget,
        include_comments: bool,
        retention: RetentionPolicy,
    ) -> list[EvidenceRecord]:
        try:
            raw = self.source.fetch(candidate.canonical_id, include_comments=include_comments)
        except DataSourceError as exc:
            if exc.category == "rate_limited":
                raise PlatformCircuitBreak("http_412", str(exc)) from exc
            raise CandidateReadError(f"video_{exc.category}", str(exc)) from exc
        except ValueError as exc:
            raise CandidateReadError("invalid_candidate", str(exc)) from exc

        subject_id = raw.metadata.bvid or candidate.canonical_id
        source_url = raw.metadata.webpage_url or candidate.url
        records = [
            EvidenceRecord(
                evidence_id=_evidence_id(subject_id, "description", "0"),
                subject_id=subject_id,
                source_kind="description",
                source_url=source_url,
                text=_retained_text(raw.metadata.description, retention, limit=2_000),
                attributes={
                    "title": raw.metadata.title,
                    "published_at": (
                        raw.metadata.publish_time.isoformat()
                        if raw.metadata.publish_time is not None
                        else None
                    ),
                    "views": raw.metadata.views,
                    "likes": raw.metadata.likes,
                    "favorites": raw.metadata.favorites,
                    "coins": raw.metadata.coins,
                    "warnings": raw.warnings,
                },
            )
        ]
        for index, track in enumerate(raw.subtitles):
            records.append(
                EvidenceRecord(
                    evidence_id=_evidence_id(subject_id, "subtitle", f"{track.language}:{index}"),
                    subject_id=subject_id,
                    source_kind="subtitle",
                    source_url=source_url,
                    text=_retained_text(track.text, retention, limit=4_000),
                    attributes={"language": track.language},
                )
            )
        if include_comments:
            for index, comment in enumerate(raw.comments[:20]):
                records.append(
                    EvidenceRecord(
                        evidence_id=_evidence_id(subject_id, "comment", str(index)),
                        subject_id=subject_id,
                        source_kind="comment",
                        source_url=source_url,
                        text=_retained_text(comment.text, retention, limit=500),
                        attributes={
                            "likes": comment.likes,
                            "published_at": (
                                comment.published_at.isoformat()
                                if comment.published_at is not None
                                else None
                            ),
                        },
                    )
                )
        return records
