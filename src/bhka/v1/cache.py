from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .contracts import (
    DiscoveryCandidate,
    EvidenceRecord,
    IntentProfile,
    ResourceRecord,
    RetentionPolicy,
    VerificationScope,
)

_SENSITIVE_ATTRIBUTE_PARTS = {
    "authorization",
    "cookie",
    "formats",
    "headers",
    "media_url",
    "request_header",
    "token",
}


def intent_cache_key(intent: IntentProfile) -> str:
    normalized = {
        "mode": intent.mode.value,
        "goal": " ".join(intent.goal.casefold().split()),
        "constraints": sorted(" ".join(item.casefold().split()) for item in intent.constraints),
    }
    payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _safe_attributes(value: Any) -> Any:
    if isinstance(value, dict):
        output = {}
        for key, item in value.items():
            normalized_key = str(key).casefold()
            if any(part in normalized_key for part in _SENSITIVE_ATTRIBUTE_PARTS):
                continue
            output[str(key)] = _safe_attributes(item)
        return output
    if isinstance(value, list):
        return [_safe_attributes(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class SQLiteCheckpointStore:
    """Small local cache with per-intent candidate reuse and incremental evidence writes."""

    def __init__(
        self,
        path: Path,
        *,
        retain_full_text: bool = False,
        excerpt_characters: int = 800,
        evidence_ttl: timedelta = timedelta(days=7),
        resource_ttl: timedelta = timedelta(days=7),
        clock: Callable[[], datetime] | None = None,
    ):
        if excerpt_characters < 100:
            raise ValueError("excerpt_characters must be at least 100")
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.retain_full_text = retain_full_text
        self.excerpt_characters = excerpt_characters
        self.evidence_ttl = evidence_ttl
        self.resource_ttl = resource_ttl
        self._clock = clock or (lambda: datetime.now(UTC))
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS candidate (
                    canonical_id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    creator_name TEXT,
                    provenance_json TEXT NOT NULL,
                    matched_queries_json TEXT NOT NULL,
                    local_score REAL NOT NULL,
                    local_score_reasons_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS intent_candidate (
                    intent_key TEXT NOT NULL,
                    canonical_id TEXT NOT NULL,
                    discovered_at TEXT NOT NULL,
                    PRIMARY KEY (intent_key, canonical_id),
                    FOREIGN KEY (canonical_id) REFERENCES candidate(canonical_id)
                );
                CREATE TABLE IF NOT EXISTS evidence (
                    evidence_id TEXT PRIMARY KEY,
                    subject_id TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    collected_at TEXT NOT NULL,
                    text_excerpt TEXT,
                    attributes_json TEXT NOT NULL,
                    cached INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS evidence_snapshot (
                    subject_id TEXT PRIMARY KEY,
                    include_comments INTEGER NOT NULL,
                    retention TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS event (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    status TEXT NOT NULL,
                    code TEXT
                );
                CREATE TABLE IF NOT EXISTS resource (
                    locator TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    verification_scope TEXT NOT NULL DEFAULT 'none'
                );
                """
            )
            resource_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(resource)")
            }
            if "verification_scope" not in resource_columns:
                connection.execute(
                    "ALTER TABLE resource ADD COLUMN verification_scope "
                    "TEXT NOT NULL DEFAULT 'none'"
                )

    def _is_fresh(self, timestamp: str, ttl: timedelta) -> bool:
        try:
            stored_at = datetime.fromisoformat(timestamp)
        except ValueError:
            return False
        if stored_at.tzinfo is None:
            stored_at = stored_at.replace(tzinfo=UTC)
        return self._clock() - stored_at <= ttl

    def load_candidates(self, intent: IntentProfile) -> list[DiscoveryCandidate]:
        key = intent_cache_key(intent)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT candidate.*
                FROM candidate
                JOIN intent_candidate USING (canonical_id)
                WHERE intent_candidate.intent_key = ?
                ORDER BY candidate.local_score DESC, candidate.updated_at DESC
                """,
                (key,),
            ).fetchall()
        return [
            DiscoveryCandidate(
                canonical_id=row["canonical_id"],
                url=row["url"],
                title=row["title"],
                summary=row["summary"],
                creator_name=row["creator_name"],
                provenance=json.loads(row["provenance_json"]),
                matched_queries=json.loads(row["matched_queries_json"]),
                local_score=row["local_score"],
                local_score_reasons=json.loads(row["local_score_reasons_json"]),
            )
            for row in rows
        ]

    def save_candidates(
        self,
        intent: IntentProfile,
        candidates: Iterable[DiscoveryCandidate],
    ) -> None:
        key = intent_cache_key(intent)
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            for candidate in candidates:
                connection.execute(
                    """
                    INSERT INTO candidate VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(canonical_id) DO UPDATE SET
                        url=excluded.url,
                        title=excluded.title,
                        summary=excluded.summary,
                        creator_name=excluded.creator_name,
                        provenance_json=excluded.provenance_json,
                        matched_queries_json=excluded.matched_queries_json,
                        local_score=excluded.local_score,
                        local_score_reasons_json=excluded.local_score_reasons_json,
                        updated_at=excluded.updated_at
                    """,
                    (
                        candidate.canonical_id,
                        candidate.url,
                        candidate.title,
                        candidate.summary,
                        candidate.creator_name,
                        json.dumps(candidate.provenance, ensure_ascii=False),
                        json.dumps(candidate.matched_queries, ensure_ascii=False),
                        candidate.local_score,
                        json.dumps(candidate.local_score_reasons, ensure_ascii=False),
                        now,
                    ),
                )
                connection.execute(
                    """
                    INSERT OR REPLACE INTO intent_candidate
                    (intent_key, canonical_id, discovered_at) VALUES (?, ?, ?)
                    """,
                    (key, candidate.canonical_id, now),
                )

    def load_evidence(
        self,
        subject_id: str,
        *,
        include_comments: bool,
        retention: RetentionPolicy,
    ) -> list[EvidenceRecord] | None:
        with self._connect() as connection:
            snapshot = connection.execute(
                "SELECT * FROM evidence_snapshot WHERE subject_id = ?",
                (subject_id,),
            ).fetchone()
            if snapshot is None or not self._is_fresh(snapshot["updated_at"], self.evidence_ttl):
                return None
            if include_comments and not bool(snapshot["include_comments"]):
                return None
            try:
                cached_retention = RetentionPolicy(snapshot["retention"])
            except ValueError:
                return None
            if (
                retention == RetentionPolicy.FULL_EVIDENCE
                and cached_retention != RetentionPolicy.FULL_EVIDENCE
            ):
                return None
            rows = connection.execute(
                "SELECT * FROM evidence WHERE subject_id = ? ORDER BY collected_at, evidence_id",
                (subject_id,),
            ).fetchall()
        try:
            return [
                EvidenceRecord(
                    evidence_id=row["evidence_id"],
                    subject_id=row["subject_id"],
                    source_kind=row["source_kind"],
                    source_url=row["source_url"],
                    collected_at=datetime.fromisoformat(row["collected_at"]),
                    text=row["text_excerpt"],
                    attributes=json.loads(row["attributes_json"]),
                    cached=True,
                )
                for row in rows
                if include_comments or row["source_kind"] != "comment"
            ]
        except ValueError:
            return None

    def load_resource(
        self,
        locator: str,
        *,
        scope: VerificationScope,
    ) -> ResourceRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM resource WHERE locator = ?",
                (locator,),
            ).fetchone()
        if row is None or not self._is_fresh(row["updated_at"], self.resource_ttl):
            return None
        scope_rank = {
            VerificationScope.NONE: 0,
            VerificationScope.CORE: 1,
            VerificationScope.ALL: 2,
        }
        try:
            cached_scope = VerificationScope(row["verification_scope"])
        except ValueError:
            return None
        if scope_rank[cached_scope] < scope_rank[scope]:
            return None
        try:
            return ResourceRecord.model_validate_json(row["payload_json"])
        except ValueError:
            return None

    def save_evidence(self, evidence: Iterable[EvidenceRecord]) -> None:
        with self._connect() as connection:
            self._save_evidence(connection, evidence)

    def _save_evidence(
        self,
        connection: sqlite3.Connection,
        evidence: Iterable[EvidenceRecord],
        *,
        truncate: bool = True,
    ) -> None:
        for record in evidence:
            text = record.text
            if text is not None and truncate and not self.retain_full_text:
                text = text[: self.excerpt_characters]
            connection.execute(
                """
                INSERT OR REPLACE INTO evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.evidence_id,
                    record.subject_id,
                    record.source_kind,
                    record.source_url,
                    record.collected_at.isoformat(),
                    text,
                    json.dumps(_safe_attributes(record.attributes), ensure_ascii=False),
                    int(record.cached),
                ),
            )

    def save_evidence_snapshot(
        self,
        subject_id: str,
        evidence: Iterable[EvidenceRecord],
        *,
        include_comments: bool,
        retention: RetentionPolicy,
    ) -> None:
        records = list(evidence)
        effective_retention = (
            retention if self.retain_full_text else RetentionPolicy.MINIMAL
        )
        with self._connect() as connection:
            connection.execute("DELETE FROM evidence WHERE subject_id = ?", (subject_id,))
            self._save_evidence(
                connection,
                records,
                truncate=(
                    retention == RetentionPolicy.FULL_EVIDENCE
                    and not self.retain_full_text
                ),
            )
            connection.execute(
                """
                INSERT INTO evidence_snapshot VALUES (?, ?, ?, ?)
                ON CONFLICT(subject_id) DO UPDATE SET
                    include_comments=excluded.include_comments,
                    retention=excluded.retention,
                    updated_at=excluded.updated_at
                """,
                (
                    subject_id,
                    int(include_comments),
                    effective_retention.value,
                    self._clock().isoformat(),
                ),
            )

    def record_event(self, phase: str, status: str, code: str | None = None) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO event (timestamp, phase, status, code) VALUES (?, ?, ?, ?)",
                (datetime.now(UTC).isoformat(), phase, status, code),
            )

    def save_resources(
        self,
        resources: Iterable[ResourceRecord],
        *,
        verification_scope: VerificationScope = VerificationScope.NONE,
    ) -> None:
        now = self._clock().isoformat()
        with self._connect() as connection:
            for resource in resources:
                connection.execute(
                    """
                    INSERT INTO resource
                    (locator, payload_json, updated_at, verification_scope)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(locator) DO UPDATE SET
                        payload_json=excluded.payload_json,
                        updated_at=excluded.updated_at,
                        verification_scope=excluded.verification_scope
                    """,
                    (
                        resource.locator,
                        resource.model_dump_json(),
                        now,
                        verification_scope.value,
                    ),
                )
