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
    RetentionPolicy,
    RunEvent,
    RunOutcome,
    VerificationScope,
)
from .evidence_reader import YtDlpEvidenceReader
from .pipeline import CandidateReadError, PlatformCircuitBreak, V1DiscoveryPipeline
from .ranking import DeterministicCandidateRanker
from .search_page import SearchPageCandidateParser
from .search_session import BilibiliSearchPageDiscoverer, ManagedEdgeSearchSession

__all__ = [
    "BilibiliSearchPageDiscoverer",
    "Breadth",
    "CandidateReadError",
    "DeterministicCandidateRanker",
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
    "SQLiteCheckpointStore",
    "SearchPageCandidateParser",
    "V1DiscoveryPipeline",
    "VerificationScope",
    "YtDlpEvidenceReader",
]
