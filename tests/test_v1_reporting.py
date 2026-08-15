import json

from bhka.v1.contracts import (
    DiscoveryCandidate,
    DiscoveryMode,
    EvidenceRecord,
    IntentProfile,
    NetworkBudget,
    QueryPlan,
    QuerySpec,
    RunOutcome,
)
from bhka.v1.reporting import ReportWriter


def outcome(status="success"):
    intent = IntentProfile(
        original_request="学习 KiCad PCB",
        goal="学习 KiCad PCB",
        mode=DiscoveryMode.LEARNING,
    )
    candidate = DiscoveryCandidate(
        canonical_id="BV1",
        url="https://www.bilibili.com/video/BV1",
        title="KiCad PCB 教程",
        local_score=8,
    )
    return RunOutcome(
        status=status,
        intent=intent,
        query_plan=QueryPlan(
            queries=[QuerySpec(text="KiCad PCB", purpose="precise")],
            candidate_target=5,
            selected_target=3,
            deep_read_target=1,
        ),
        budget=NetworkBudget(),
        candidates=[candidate],
        selected_candidates=[candidate],
        evidence=[
            EvidenceRecord(
                evidence_id="e1",
                subject_id="BV1",
                source_kind="subtitle",
                source_url=candidate.url,
                text="字" * 1_000,
                attributes={"language": "zh-CN", "request_headers": {"Cookie": "secret"}},
            )
        ],
    )


def test_writer_outputs_utf8_json_markdown_and_latest_pointer(tmp_path):
    paths = ReportWriter(tmp_path).write(outcome())

    payload = json.loads(paths.json_path.read_text(encoding="utf-8"))
    markdown = paths.markdown_path.read_text(encoding="utf-8")
    assert payload["intent"]["original_request"] == "学习 KiCad PCB"
    assert len(payload["evidence"][0]["text"]) == 800
    assert "request_headers" not in payload["evidence"][0]["attributes"]
    assert "精选视频" in markdown
    assert paths.latest_json_path == tmp_path / "latest.json"


def test_failed_run_does_not_replace_latest_success(tmp_path):
    writer = ReportWriter(tmp_path)
    success = outcome("success")
    writer.write(success)
    failed = outcome("failed")
    paths = writer.write(failed)

    assert json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))["run_id"] == success.run_id
    assert paths.latest_json_path == tmp_path / "latest-failed.json"
