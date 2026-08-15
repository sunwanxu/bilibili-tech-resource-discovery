from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


class DiscoveryMode(StrEnum):
    LEARNING = "learning"
    RESOURCE = "resource"


class Breadth(StrEnum):
    FAST = "fast"
    STANDARD = "standard"
    DEEP = "deep"


class VerificationScope(StrEnum):
    NONE = "none"
    CORE = "core"
    ALL = "all"


class RetentionPolicy(StrEnum):
    MINIMAL = "minimal"
    FULL_EVIDENCE = "full_evidence"


class IntentProfile(BaseModel):
    """The host-facing, platform-independent interpretation of a user request."""

    original_request: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    mode: DiscoveryMode
    user_level: str | None = None
    constraints: list[str] = Field(default_factory=list)
    breadth: Breadth = Breadth.STANDARD
    verification_scope: VerificationScope = VerificationScope.CORE
    retention: RetentionPolicy = RetentionPolicy.MINIMAL
    login_allowed: bool = False


class QuerySpec(BaseModel):
    text: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    required_anchors: list[str] = Field(default_factory=list)
    priority: int = Field(default=1, ge=1, le=10)


class QueryPlan(BaseModel):
    queries: list[QuerySpec] = Field(min_length=1, max_length=4)
    candidate_target: int = Field(default=20, ge=5, le=80)
    selected_target: int = Field(default=8, ge=3, le=20)
    deep_read_target: int = Field(default=6, ge=0, le=15)

    @model_validator(mode="after")
    def validate_targets(self) -> QueryPlan:
        if self.selected_target > self.candidate_target:
            raise ValueError("selected_target cannot exceed candidate_target")
        if self.deep_read_target > self.selected_target:
            raise ValueError("deep_read_target cannot exceed selected_target")
        return self


class NetworkBudget(BaseModel):
    """A run-wide budget. Every Bilibili-facing adapter consumes from the same object."""

    bilibili_requests_limit: int = Field(default=12, ge=1, le=100)
    external_requests_limit: int = Field(default=20, ge=0, le=200)
    bilibili_requests_used: int = Field(default=0, ge=0)
    external_requests_used: int = Field(default=0, ge=0)
    circuit_open: bool = False
    circuit_reason: str | None = None

    def allow_bilibili(self) -> bool:
        return not self.circuit_open and (
            self.bilibili_requests_used < self.bilibili_requests_limit
        )

    def consume_bilibili(self) -> None:
        if not self.allow_bilibili():
            raise RuntimeError("Bilibili request budget is unavailable")
        self.bilibili_requests_used += 1

    def allow_external(self) -> bool:
        return self.external_requests_used < self.external_requests_limit

    def consume_external(self) -> None:
        if not self.allow_external():
            raise RuntimeError("External request budget is unavailable")
        self.external_requests_used += 1

    def open_circuit(self, reason: str) -> None:
        self.circuit_open = True
        self.circuit_reason = reason


class DiscoveryCandidate(BaseModel):
    canonical_id: str
    url: str
    title: str = ""
    summary: str = ""
    creator_name: str | None = None
    provenance: list[str] = Field(default_factory=list)
    matched_queries: list[str] = Field(default_factory=list)
    local_score: float = 0
    local_score_reasons: list[str] = Field(default_factory=list)


class EvidenceRecord(BaseModel):
    evidence_id: str
    subject_id: str
    source_kind: Literal[
        "search_result",
        "description",
        "subtitle",
        "comment",
        "related_video",
        "creator_page",
        "article",
        "external_resource",
        "user_input",
    ]
    source_url: str
    collected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    text: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    cached: bool = False


class ResourceKind(StrEnum):
    REPOSITORY = "repository"
    PCB_PROJECT = "pcb_project"
    SHARED_FILE = "shared_file"
    DOCUMENT = "document"
    COMMUNITY = "community"
    UNKNOWN = "unknown"


class ResourceAccessStatus(StrEnum):
    ACCESSIBLE = "accessible"
    LOGIN_OR_MANUAL = "login_or_manual_access"
    DEAD = "dead_link"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class ResourceLicenseStatus(StrEnum):
    VERIFIED = "verified_license"
    PUBLIC_NO_LICENSE = "public_source_no_license"
    CLAIMED_NO_LINK = "claimed_open_no_link"
    AUTHORIZATION_UNCLEAR = "downloadable_authorization_unclear"
    LOGIN_OR_MANUAL = "login_or_manual_access"
    DEAD = "dead_link"
    NO_EVIDENCE = "no_open_source_evidence"


class ResourceOrigin(BaseModel):
    evidence_id: str
    source_kind: str
    source_url: str
    context: str = ""


class ResourceRecord(BaseModel):
    locator: str
    repository_root: str | None = None
    host: str
    kind: ResourceKind = ResourceKind.UNKNOWN
    origins: list[ResourceOrigin] = Field(default_factory=list)
    access_status: ResourceAccessStatus = ResourceAccessStatus.UNKNOWN
    license_status: ResourceLicenseStatus = ResourceLicenseStatus.NO_EVIDENCE
    license_name: str | None = None
    license_scope: str | None = None
    artifacts: list[str] = Field(default_factory=list)
    verification_notes: list[str] = Field(default_factory=list)
    value_score: float = Field(default=0, ge=0, le=10)
    value_reasons: list[str] = Field(default_factory=list)


class RunEvent(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    phase: str
    status: str
    code: str | None = None
    detail: str | None = None
    request_kind: Literal["none", "bilibili", "external"] = "none"


class RunOutcome(BaseModel):
    schema_version: str = "1.0.0-draft"
    run_id: str = Field(
        default_factory=lambda: (
            datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex[:8]
        )
    )
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: Literal["success", "partial_success", "failed"]
    intent: IntentProfile
    query_plan: QueryPlan
    budget: NetworkBudget
    candidates: list[DiscoveryCandidate] = Field(default_factory=list)
    selected_candidates: list[DiscoveryCandidate] = Field(default_factory=list)
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    resources: list[ResourceRecord] = Field(default_factory=list)
    events: list[RunEvent] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
