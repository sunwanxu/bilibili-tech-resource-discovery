"""Version-one pipeline contracts.

The v1 package is intentionally isolated from the v0.8 runtime until its user-flow and
low-rate network tests pass.
"""

from .cache import SQLiteCheckpointStore
from .contracts import (
    Breadth,
    DiscoveryCandidate,
    DiscoveryMode,
    EvidenceRecord,
    IntentProfile,
    NetworkBudget,
    QueryPlan,
    QuerySpec,
    ResourceAccessStatus,
    ResourceKind,
    ResourceLicenseStatus,
    ResourceOrigin,
    ResourceRecord,
    RetentionPolicy,
    RunEvent,
    RunOutcome,
    VerificationScope,
)
from .evidence_reader import YtDlpEvidenceReader
from .pipeline import (
    CandidateReadError,
    DiscoveryFailure,
    PlatformCircuitBreak,
    ResourceVerificationFailure,
    V1DiscoveryPipeline,
)
from .planner import StableQueryPlanner
from .ranking import DeterministicCandidateRanker
from .reporting import ReportWriter
from .resource_extraction import EvidenceResourceExtractor
from .resource_verification import ResourceVerifierRouter
from .search_page import SearchPageCandidateParser
from .search_session import BilibiliSearchPageDiscoverer, ManagedEdgeSearchSession

__all__ = [
    "BilibiliSearchPageDiscoverer",
    "Breadth",
    "CandidateReadError",
    "DeterministicCandidateRanker",
    "DiscoveryCandidate",
    "DiscoveryFailure",
    "DiscoveryMode",
    "EvidenceRecord",
    "EvidenceResourceExtractor",
    "IntentProfile",
    "ManagedEdgeSearchSession",
    "NetworkBudget",
    "PlatformCircuitBreak",
    "QueryPlan",
    "QuerySpec",
    "ReportWriter",
    "ResourceAccessStatus",
    "ResourceKind",
    "ResourceLicenseStatus",
    "ResourceOrigin",
    "ResourceRecord",
    "ResourceVerificationFailure",
    "ResourceVerifierRouter",
    "RetentionPolicy",
    "RunEvent",
    "RunOutcome",
    "SQLiteCheckpointStore",
    "SearchPageCandidateParser",
    "StableQueryPlanner",
    "V1DiscoveryPipeline",
    "VerificationScope",
    "YtDlpEvidenceReader",
]
