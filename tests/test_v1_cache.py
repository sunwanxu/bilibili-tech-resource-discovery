import json
import sqlite3

from bhka.v1.cache import SQLiteCheckpointStore, intent_cache_key
from bhka.v1.contracts import (
    DiscoveryCandidate,
    DiscoveryMode,
    EvidenceRecord,
    IntentProfile,
    ResourceKind,
    ResourceRecord,
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
