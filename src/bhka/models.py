from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class Comment(BaseModel):
    author: str | None = None
    text: str
    likes: int | None = None
    published_at: datetime | None = None


class SubtitleTrack(BaseModel):
    language: str
    text: str


class VideoMetadata(BaseModel):
    bvid: str
    title: str
    description: str = ""
    author: str | None = None
    publish_time: datetime | None = None
    views: int | None = None
    likes: int | None = None
    favorites: int | None = None
    coins: int | None = None
    comments_count: int | None = None
    tags: list[str] = Field(default_factory=list)
    duration_seconds: float | None = None
    webpage_url: str
    part_number: int | None = None
    part_title: str | None = None


class VideoPart(BaseModel):
    bvid: str
    page: int
    cid: int
    title: str
    duration_seconds: float | None = None
    webpage_url: str


class PartSelection(BaseModel):
    role: str
    reason: str
    part: VideoPart


class RawVideoData(BaseModel):
    fetched_at: datetime
    source: str
    metadata: VideoMetadata
    subtitles: list[SubtitleTrack] = Field(default_factory=list)
    comments: list[Comment] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SearchResult(BaseModel):
    source_id: str
    webpage_url: str
    query: str
    rank: int
    provenance: str = "bilibili_search"
    title: str = ""
    description: str = ""


class AuthenticationStatus(BaseModel):
    configured: bool
    is_login: bool | None
    status: Literal["unconfigured", "valid", "invalid"]


class SearchCandidate(BaseModel):
    source_id: str
    webpage_url: str
    title: str = ""
    description: str = ""
    matched_queries: list[str] = Field(default_factory=list)
    best_rank: int
    discovery_score: float
    provenance: list[str] = Field(default_factory=list)


class DiscoveryEvent(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    phase: str
    status: str
    query: str | None = None
    detail: str | None = None


class ExternalResource(BaseModel):
    locator: str
    kind: str
    origin: str
    access_status: str
    license_status: str
    inspection_status: str = "not_inspected"
    artifacts: dict[str, str] = Field(default_factory=dict)
    verification_notes: list[str] = Field(default_factory=list)
    origins: list[str] = Field(default_factory=list)
    supporting_videos: list[str] = Field(default_factory=list)
    usability_status: str = "unverified"
    resource_score: float = Field(default=0, ge=0, le=10)
    resource_value_reason: str = "Not evaluated"


class DiscoveredVideo(BaseModel):
    bvid: str
    title: str
    webpage_url: str
    author: str | None = None
    views: int | None = None
    likes: int | None = None
    duration_seconds: float | None = None
    matched_queries: list[str] = Field(default_factory=list)
    discovery_score: float
    suitability_score: float = Field(ge=0, le=10)
    suitability_reason: str
    open_source_status: str
    open_source_reason: str
    resources: list[ExternalResource] = Field(default_factory=list)
    evidence_basis: list[str] = Field(default_factory=list)
    evidence_limitations: list[str] = Field(default_factory=list)


class DiscoveryReport(BaseModel):
    schema_version: str = "0.8.0"
    run_id: str = Field(
        default_factory=lambda: (
            datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex[:8]
        )
    )
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    run_status: Literal["success", "partial_success", "failed"] = "success"
    discovery_mode: Literal["learning", "resources"] = "resources"
    requirement: str
    expanded_queries: list[str]
    candidates_found: int
    deep_inspection_limit: int
    successful_queries: int = 0
    failed_queries: int = 0
    skipped_queries: int = 0
    stopped_at_query: str | None = None
    stop_reason: str | None = None
    failure_category: str | None = None
    candidates: list[SearchCandidate] = Field(default_factory=list)
    videos: list[DiscoveredVideo] = Field(default_factory=list)
    resources: list[ExternalResource] = Field(default_factory=list)
    direct_resources: list[ExternalResource] = Field(default_factory=list)
    events: list[DiscoveryEvent] = Field(default_factory=list)
    evidence_limitations: list[str] = Field(default_factory=list)


class ScoreReason(BaseModel):
    score: float = Field(ge=0, le=10)
    reason: str


class ResourceValue(BaseModel):
    score: float = Field(ge=0, le=10)
    resources: list[str] = Field(default_factory=list)


class CommentValue(BaseModel):
    score: float = Field(ge=0, le=10)
    observations: list[str] = Field(default_factory=list)


class Topic(BaseModel):
    main_topic: str
    sub_topics: list[str] = Field(default_factory=list)


class Recommendation(BaseModel):
    score: float = Field(ge=0, le=10)
    should_watch: bool
    reason: str


class VideoRef(BaseModel):
    bvid: str
    title: str


class VideoAnalysisSchema(BaseModel):
    schema_version: str = "0.1.0"
    analysis_method: str
    evidence_limitations: list[str] = Field(default_factory=list)
    video: VideoRef
    topic: Topic
    content_type: list[str] = Field(default_factory=list)
    difficulty: ScoreReason
    technical_depth: ScoreReason
    engineering_value: ScoreReason
    practical_value: ScoreReason
    resource_value: ResourceValue
    comment_value: CommentValue
    knowledge_density: ScoreReason
    possible_hidden_value: ScoreReason
    important_knowledge: list[str] = Field(default_factory=list)
    target_audience: list[str] = Field(default_factory=list)
    recommendation: Recommendation
