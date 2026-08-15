from datetime import UTC, datetime

import pytest

from bhka.models import Comment, RawVideoData, SubtitleTrack, VideoMetadata
from bhka.source import DataSourceError
from bhka.v1.contracts import (
    DiscoveryCandidate,
    NetworkBudget,
    RetentionPolicy,
)
from bhka.v1.evidence_reader import YtDlpEvidenceReader
from bhka.v1.pipeline import CandidateReadError, PlatformCircuitBreak


def candidate():
    return DiscoveryCandidate(
        canonical_id="BV1234567890",
        url="https://www.bilibili.com/video/BV1234567890",
        title="PCB project",
    )


class Source:
    def fetch(self, video, include_comments=False, part=None):
        assert video == "BV1234567890"
        return RawVideoData(
            fetched_at=datetime.now(UTC),
            source="yt-dlp",
            metadata=VideoMetadata(
                bvid=video,
                title="STM32 PCB 开源工程",
                description="d" * 3_000,
                webpage_url=f"https://www.bilibili.com/video/{video}",
            ),
            subtitles=[SubtitleTrack(language="ai-zh", text="s" * 5_000)],
            comments=(
                [Comment(author="private-name", text="c" * 600, likes=5)]
                if include_comments
                else []
            ),
        )


def test_minimal_reader_bounds_text_and_drops_comment_author():
    records = YtDlpEvidenceReader(Source()).read(
        candidate(),
        budget=NetworkBudget(),
        include_comments=True,
        retention=RetentionPolicy.MINIMAL,
    )

    assert [record.source_kind for record in records] == ["description", "subtitle", "comment"]
    assert len(records[0].text) == 2_000
    assert len(records[1].text) == 4_000
    assert len(records[2].text) == 500
    assert "author" not in records[2].attributes


def test_full_retention_keeps_complete_subtitle_only_when_selected():
    records = YtDlpEvidenceReader(Source()).read(
        candidate(),
        budget=NetworkBudget(),
        include_comments=False,
        retention=RetentionPolicy.FULL_EVIDENCE,
    )

    assert len(records[1].text) == 5_000


class FailingSource:
    def __init__(self, category):
        self.category = category

    def fetch(self, video, include_comments=False, part=None):
        raise DataSourceError("bounded failure", category=self.category)


def test_reader_maps_412_to_global_circuit():
    with pytest.raises(PlatformCircuitBreak):
        YtDlpEvidenceReader(FailingSource("rate_limited")).read(
            candidate(),
            budget=NetworkBudget(),
            include_comments=False,
            retention=RetentionPolicy.MINIMAL,
        )


def test_reader_maps_other_source_failures_to_one_candidate_error():
    with pytest.raises(CandidateReadError) as error:
        YtDlpEvidenceReader(FailingSource("authentication")).read(
            candidate(),
            budget=NetworkBudget(),
            include_comments=False,
            retention=RetentionPolicy.MINIMAL,
        )

    assert error.value.code == "video_authentication"

