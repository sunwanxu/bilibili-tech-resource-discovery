from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from .contracts import (
    DiscoveryCandidate,
    EvidenceRecord,
    IntentProfile,
    NetworkBudget,
    QuerySpec,
    RetentionPolicy,
)


class CandidateDiscoverer(Protocol):
    """Find candidates without deciding which of them is valuable."""

    def discover(
        self,
        query: QuerySpec,
        *,
        budget: NetworkBudget,
    ) -> Iterable[DiscoveryCandidate]: ...


class CandidateRanker(Protocol):
    """Pure/local ranking boundary; implementations must not perform network requests."""

    def rank(
        self,
        intent: IntentProfile,
        candidates: Iterable[DiscoveryCandidate],
    ) -> list[DiscoveryCandidate]: ...


class EvidenceReader(Protocol):
    """Read bounded evidence for one already-selected candidate."""

    def read(
        self,
        candidate: DiscoveryCandidate,
        *,
        budget: NetworkBudget,
        include_comments: bool,
        retention: RetentionPolicy,
    ) -> Iterable[EvidenceRecord]: ...


class CheckpointStore(Protocol):
    def load_candidates(self, intent: IntentProfile) -> list[DiscoveryCandidate]: ...

    def save_candidates(
        self,
        intent: IntentProfile,
        candidates: Iterable[DiscoveryCandidate],
    ) -> None: ...

    def save_evidence(self, evidence: Iterable[EvidenceRecord]) -> None: ...

    def record_event(self, phase: str, status: str, code: str | None = None) -> None: ...
