import json
import sqlite3
from datetime import UTC, datetime, timedelta

from bhka.v1.cache import SQLiteCheckpointStore, intent_cache_key
from bhka.v1.contracts import (
    DiscoveryCandidate,
    DiscoveryMode,
    EvidenceRecord,
    IntentProfile,
    ResourceKind,
    ResourceLicenseStatus,
    ResourceRecord,
    RetentionPolicy,
    VerificationScope,
)


def make_intent(goal="找到 STM32 PCB 项目"):
    return IntentProfile(
        original_request=goal,
        goal=goal,
        mode=DiscoveryMode.RESOURCE,
    )


def test_cache_reuses_candidates_only_for_same_normalized_intent(tmp_path):
    store = SQLiteCheckpointStore(tmp_path / "cache.sqlite3")
    first = make_intent()
    equivalent = make_intent("  找到   STM32 PCB 项目  ")
    different = make_intent("学习 FastAPI")
    candidate = DiscoveryCandidate(
        canonical_id="BV1",
        url="https://www.bilibili.com/video/BV1",
        title="STM32 PCB 开源项目",
    )

    store.save_candidates(first, [candidate])

    assert intent_cache_key(first) == intent_cache_key(equivalent)
    assert [item.canonical_id for item in store.load_candidates(equivalent)] == ["BV1"]
    assert store.load_candidates(different) == []


def test_minimal_evidence_cache_truncates_text_and_drops_sensitive_attributes(tmp_path):
    path = tmp_path / "cache.sqlite3"
    store = SQLiteCheckpointStore(path, excerpt_characters=100)
    store.save_evidence(
        [
            EvidenceRecord(
                evidence_id="e1",
                subject_id="BV1",
                source_kind="description",
                source_url="https://www.bilibili.com/video/BV1",
                text="x" * 200,
                attributes={
                    "language": "zh",
                    "request_headers": {"Cookie": "secret"},
                    "token": "secret",
                },
            )
        ]
    )

    with sqlite3.connect(path) as connection:
        text, attributes = connection.execute(
            "SELECT text_excerpt, attributes_json FROM evidence WHERE evidence_id='e1'"
        ).fetchone()

    assert len(text) == 100
    assert json.loads(attributes) == {"language": "zh"}


def test_resource_checkpoint_is_valid_json_and_updates_in_place(tmp_path):
    path = tmp_path / "cache.sqlite3"
    store = SQLiteCheckpointStore(path)
    resource = ResourceRecord(
        locator="https://github.com/acme/board",
        repository_root="https://github.com/acme/board",
        host="github.com",
        kind=ResourceKind.REPOSITORY,
    )
    store.save_resources([resource])
    resource.license_name = "MIT"
    store.save_resources([resource])

    with sqlite3.connect(path) as connection:
        rows = connection.execute("SELECT payload_json FROM resource").fetchall()

    assert len(rows) == 1
    assert json.loads(rows[0][0])["license_name"] == "MIT"


def test_evidence_snapshot_reuses_only_sufficient_fresh_evidence(tmp_path):
    now = [datetime(2026, 8, 15, tzinfo=UTC)]
    store = SQLiteCheckpointStore(
        tmp_path / "cache.sqlite3",
        excerpt_characters=100,
        clock=lambda: now[0],
    )
    record = EvidenceRecord(
        evidence_id="description-BV1",
        subject_id="BV1",
        source_kind="description",
        source_url="https://www.bilibili.com/video/BV1",
        text="x" * 200,
    )
    store.save_evidence_snapshot(
        "BV1",
        [record],
        include_comments=False,
        retention=RetentionPolicy.MINIMAL,
    )

    cached = store.load_evidence(
        "BV1",
        include_comments=False,
        retention=RetentionPolicy.MINIMAL,
    )

    assert cached is not None
    assert cached[0].cached is True
    assert cached[0].text == "x" * 200
    assert (
        store.load_evidence(
            "BV1",
            include_comments=True,
            retention=RetentionPolicy.MINIMAL,
        )
        is None
    )
    assert (
        store.load_evidence(
            "BV1",
            include_comments=False,
            retention=RetentionPolicy.FULL_EVIDENCE,
        )
        is None
    )

    now[0] += timedelta(days=8)
    assert (
        store.load_evidence(
            "BV1",
            include_comments=False,
            retention=RetentionPolicy.MINIMAL,
        )
        is None
    )


def test_full_evidence_cache_requires_explicit_full_text_retention(tmp_path):
    store = SQLiteCheckpointStore(
        tmp_path / "cache.sqlite3",
        retain_full_text=True,
    )
    record = EvidenceRecord(
        evidence_id="subtitle-BV1",
        subject_id="BV1",
        source_kind="subtitle",
        source_url="https://www.bilibili.com/video/BV1",
        text="完整字幕",
    )
    store.save_evidence_snapshot(
        "BV1",
        [record],
        include_comments=True,
        retention=RetentionPolicy.FULL_EVIDENCE,
    )

    cached = store.load_evidence(
        "BV1",
        include_comments=True,
        retention=RetentionPolicy.FULL_EVIDENCE,
    )

    assert cached is not None
    assert cached[0].text == "完整字幕"


def test_resource_cache_respects_verification_scope_and_expiration(tmp_path):
    now = [datetime(2026, 8, 15, tzinfo=UTC)]
    store = SQLiteCheckpointStore(
        tmp_path / "cache.sqlite3",
        resource_ttl=timedelta(days=2),
        clock=lambda: now[0],
    )
    resource = ResourceRecord(
        locator="https://github.com/acme/board",
        repository_root="https://github.com/acme/board",
        host="github.com",
        kind=ResourceKind.REPOSITORY,
        license_status=ResourceLicenseStatus.VERIFIED,
        license_name="MIT",
    )
    store.save_resources([resource], verification_scope=VerificationScope.CORE)

    assert store.load_resource(resource.locator, scope=VerificationScope.CORE) is not None
    assert store.load_resource(resource.locator, scope=VerificationScope.ALL) is None

    now[0] += timedelta(days=3)
    assert store.load_resource(resource.locator, scope=VerificationScope.CORE) is None


def test_existing_resource_table_is_migrated_without_losing_rows(tmp_path):
    path = tmp_path / "cache.sqlite3"
    resource = ResourceRecord(
        locator="https://github.com/acme/legacy",
        repository_root="https://github.com/acme/legacy",
        host="github.com",
        kind=ResourceKind.REPOSITORY,
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE resource "
            "(locator TEXT PRIMARY KEY, payload_json TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO resource VALUES (?, ?, ?)",
            (resource.locator, resource.model_dump_json(), datetime.now(UTC).isoformat()),
        )

    SQLiteCheckpointStore(path)

    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(resource)")}
        count = connection.execute("SELECT COUNT(*) FROM resource").fetchone()[0]
    assert "verification_scope" in columns
    assert count == 1
