from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .contracts import DiscoveryCandidate, EvidenceRecord, IntentProfile

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
    ):
        if excerpt_characters < 100:
            raise ValueError("excerpt_characters must be at least 100")
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.retain_full_text = retain_full_text
        self.excerpt_characters = excerpt_characters
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
                CREATE TABLE IF NOT EXISTS event (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    status TEXT NOT NULL,
                    code TEXT
                );
                """
            )

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

    def save_evidence(self, evidence: Iterable[EvidenceRecord]) -> None:
        with self._connect() as connection:
            for record in evidence:
                text = record.text
                if text is not None and not self.retain_full_text:
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

    def record_event(self, phase: str, status: str, code: str | None = None) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO event (timestamp, phase, status, code) VALUES (?, ?, ?, ?)",
                (datetime.now(UTC).isoformat(), phase, status, code),
            )

