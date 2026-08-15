from bhka.v1.contracts import EvidenceRecord, ResourceKind
from bhka.v1.resource_extraction import extract_resource_records, normalize_resource_url


def evidence(identifier, source_kind, text):
    return EvidenceRecord(
        evidence_id=identifier,
        subject_id="BV1",
        source_kind=source_kind,
        source_url="https://www.bilibili.com/video/BV1",
        text=text,
    )


def test_extracts_and_merges_repository_links_across_evidence_channels():
    records = extract_resource_records(
        [
            evidence("description", "description", "源码：https://github.com/acme/board/tree/main/hw。"),
            evidence("comment", "comment", "补充仓库 https://github.com/acme/board.git"),
        ]
    )

    assert len(records) == 1
    assert records[0].repository_root == "https://github.com/acme/board"
    assert records[0].kind == ResourceKind.REPOSITORY
    assert {origin.source_kind for origin in records[0].origins} == {"description", "comment"}


def test_preserves_manual_value_links_and_excludes_bilibili_video_links():
    records = extract_resource_records(
        [
            evidence(
                "description",
                "description",
                "资料 https://pan.baidu.com/s/example 视频 https://www.bilibili.com/video/BV1234567890",
            )
        ]
    )

    assert len(records) == 1
    assert records[0].kind == ResourceKind.SHARED_FILE


def test_url_normalization_is_bounded_for_malformed_ipv6():
    assert normalize_resource_url("https://[bad/path") is None

