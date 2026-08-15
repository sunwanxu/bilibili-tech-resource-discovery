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

__all__ = [
    "Breadth",
    "DiscoveryCandidate",
    "DiscoveryMode",
    "EvidenceRecord",
    "IntentProfile",
    "NetworkBudget",
    "PlatformCircuitBreak",
    "QueryPlan",
    "QuerySpec",
    "RetentionPolicy",
    "RunEvent",
    "RunOutcome",
    "V1DiscoveryPipeline",
    "VerificationScope",
]
