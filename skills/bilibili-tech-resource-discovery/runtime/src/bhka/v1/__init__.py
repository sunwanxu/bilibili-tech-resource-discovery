"""Version-one natural-language discovery pipeline."""

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
from .login import V1LoginResult, interactive_v1_login
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
    "V1LoginResult",
    "VerificationScope",
    "YtDlpEvidenceReader",
    "interactive_v1_login",
]
