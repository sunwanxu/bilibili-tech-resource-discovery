"""Version-one pipeline contracts.

The v1 package is intentionally isolated from the v0.8 runtime until its user-flow and
low-rate network tests pass.
"""

from .contracts import (
    Breadth,
    DiscoveryCandidate,
    DiscoveryMode,
    EvidenceRecord,
    IntentProfile,
    NetworkBudget,
    QueryPlan,
    QuerySpec,
    RetentionPolicy,
    RunEvent,
    RunOutcome,
    VerificationScope,
)
from .pipeline import PlatformCircuitBreak, V1DiscoveryPipeline
from .search_page import SearchPageCandidateParser
from .search_session import BilibiliSearchPageDiscoverer, ManagedEdgeSearchSession

__all__ = [
    "BilibiliSearchPageDiscoverer",
    "Breadth",
    "DiscoveryCandidate",
    "DiscoveryMode",
    "EvidenceRecord",
    "IntentProfile",
    "ManagedEdgeSearchSession",
    "NetworkBudget",
    "PlatformCircuitBreak",
    "QueryPlan",
    "QuerySpec",
    "RetentionPolicy",
    "RunEvent",
    "RunOutcome",
    "SearchPageCandidateParser",
    "V1DiscoveryPipeline",
    "VerificationScope",
]
