from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from .contracts import (
    DiscoveryCandidate,
    EvidenceRecord,
    IntentProfile,
    NetworkBudget,
    QueryPlan,
    RunEvent,
    RunOutcome,
    VerificationScope,
)
from .ports import (
    CandidateDiscoverer,
    CandidateRanker,
    CheckpointStore,
    EvidenceReader,
    ResourceExtractor,
    ResourceVerifier,
)


class PlatformCircuitBreak(RuntimeError):
    """A deterministic upstream signal after which no new Bilibili request is allowed."""

    def __init__(self, code: str, detail: str | None = None):
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


class CandidateReadError(RuntimeError):
    """A bounded failure for one candidate that must not abort the full run."""

    def __init__(self, code: str, detail: str | None = None):
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


class DiscoveryFailure(RuntimeError):
    """A bounded failure of one discovery adapter."""

    def __init__(self, code: str, detail: str | None = None):
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


class ResourceVerificationFailure(RuntimeError):
    """A bounded failure for one external resource."""

    def __init__(self, code: str, detail: str | None = None):
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


class QueryPlanner(Protocol):
    def plan(self, intent: IntentProfile) -> QueryPlan: ...


def merge_candidates(
    existing: list[DiscoveryCandidate],
    incoming: list[DiscoveryCandidate],
) -> list[DiscoveryCandidate]:
    """Deduplicate without discarding provenance or query coverage."""

    merged = {candidate.canonical_id.casefold(): candidate.model_copy(deep=True) for candidate in existing}
    for candidate in incoming:
        key = candidate.canonical_id.casefold()
        if key not in merged:
            merged[key] = candidate.model_copy(deep=True)
            continue
        current = merged[key]
        current.provenance = list(dict.fromkeys([*current.provenance, *candidate.provenance]))
        current.matched_queries = list(
            dict.fromkeys([*current.matched_queries, *candidate.matched_queries])
        )
        if not current.title and candidate.title:
            current.title = candidate.title
        if not current.summary and candidate.summary:
            current.summary = candidate.summary
    return list(merged.values())


@dataclass
class V1DiscoveryPipeline:
    planner: QueryPlanner
    discoverer: CandidateDiscoverer
    ranker: CandidateRanker
    reader: EvidenceReader
    store: CheckpointStore
    resource_extractor: ResourceExtractor | None = None
    resource_verifier: ResourceVerifier | None = None

    def run(
        self,
        intent: IntentProfile,
        *,
        budget: NetworkBudget,
        initial_candidates: Iterable[DiscoveryCandidate] = (),
        initial_evidence: Iterable[EvidenceRecord] = (),
    ) -> RunOutcome:
        plan = self.planner.plan(intent)
        events: list[RunEvent] = []
        cached_candidates = self.store.load_candidates(intent)
        seeded_candidates = list(initial_candidates)
        candidates = merge_candidates(cached_candidates, seeded_candidates)
        if cached_candidates:
            events.append(
                RunEvent(
                    phase="discovery",
                    status="cache_hit",
                    detail=f"Loaded {len(cached_candidates)} cached candidates",
                )
            )
        if seeded_candidates:
            self.store.save_candidates(intent, candidates)
            events.append(
                RunEvent(
                    phase="candidate_seed",
                    status="checkpointed",
                    detail=f"Loaded {len(seeded_candidates)} host-discovered video candidates",
                )
            )

        circuit_during_discovery = False
        for query in plan.queries:
            if len(candidates) >= plan.candidate_target:
                events.append(
                    RunEvent(
                        phase="discovery",
                        status="skipped",
                        code="candidate_target_reached",
                        detail=query.text,
                    )
                )
                continue
            if not budget.allow_bilibili():
                events.append(
                    RunEvent(
                        phase="discovery",
                        status="skipped",
                        code=budget.circuit_reason or "request_budget_exhausted",
                        detail=query.text,
                    )
                )
                continue
            try:
                budget.consume_bilibili()
                found = list(self.discoverer.discover(query, budget=budget))
            except PlatformCircuitBreak as exc:
                budget.open_circuit(exc.code)
                circuit_during_discovery = True
                events.append(
                    RunEvent(
                        phase="discovery",
                        status="circuit_open",
                        code=exc.code,
                        detail=exc.detail or query.text,
                        request_kind="bilibili",
                    )
                )
                self.store.record_event("discovery", "circuit_open", exc.code)
                continue
            except DiscoveryFailure as exc:
                events.append(
                    RunEvent(
                        phase="discovery",
                        status="failed",
                        code=exc.code,
                        detail=exc.detail or query.text,
                        request_kind="bilibili",
                    )
                )
                self.store.record_event("discovery", "failed", exc.code)
                break
            candidates = merge_candidates(candidates, found)
            self.store.save_candidates(intent, candidates)
            events.append(
                RunEvent(
                    phase="discovery",
                    status="success",
                    detail=f"{query.text}: {len(found)} candidates",
                    request_kind="bilibili",
                )
            )

        ranked = self.ranker.rank(intent, candidates)
        selected = ranked[: plan.selected_target]
        evidence = list(initial_evidence)
        if evidence:
            self.store.save_evidence(evidence)
            events.append(
                RunEvent(
                    phase="evidence_seed",
                    status="checkpointed",
                    detail=f"Loaded {len(evidence)} host-discovered external leads",
                    request_kind="external",
                )
            )

        if circuit_during_discovery:
            events.append(
                RunEvent(
                    phase="deep_read",
                    status="skipped",
                    code="circuit_open",
                    detail="No new Bilibili requests are permitted in this run",
                )
            )
        else:
            for candidate in selected[: plan.deep_read_target]:
                if not budget.allow_bilibili():
                    events.append(
                        RunEvent(
                            phase="deep_read",
                            status="skipped",
                            code=budget.circuit_reason or "request_budget_exhausted",
                            detail=candidate.canonical_id,
                        )
                    )
                    break
                try:
                    budget.consume_bilibili()
                    records = list(
                        self.reader.read(
                            candidate,
                            budget=budget,
                            include_comments=intent.mode.value == "resource",
                            retention=intent.retention,
                        )
                    )
                except PlatformCircuitBreak as exc:
                    budget.open_circuit(exc.code)
                    events.append(
                        RunEvent(
                            phase="deep_read",
                            status="circuit_open",
                            code=exc.code,
                            detail=exc.detail or candidate.canonical_id,
                            request_kind="bilibili",
                        )
                    )
                    self.store.record_event("deep_read", "circuit_open", exc.code)
                    break
                except CandidateReadError as exc:
                    events.append(
                        RunEvent(
                            phase="deep_read",
                            status="failed",
                            code=exc.code,
                            detail=exc.detail or candidate.canonical_id,
                            request_kind="bilibili",
                        )
                    )
                    self.store.record_event("deep_read", "failed", exc.code)
                    continue
                evidence.extend(records)
                self.store.save_evidence(records)
                events.append(
                    RunEvent(
                        phase="deep_read",
                        status="checkpointed",
                        detail=candidate.canonical_id,
                        request_kind="bilibili",
                    )
                )

        resources = (
            self.resource_extractor.extract(evidence)
            if self.resource_extractor is not None
            else []
        )
        if resources:
            self.store.save_resources(resources)
        if resources and intent.verification_scope == VerificationScope.NONE:
            events.append(
                RunEvent(
                    phase="resource_verification",
                    status="skipped",
                    code="resource_verification_disabled",
                    detail="Resource links were retained without access, artifact, or license checks",
                    request_kind="external",
                )
            )
        elif self.resource_verifier is not None:
            for index, resource in enumerate(resources):
                try:
                    verified = self.resource_verifier.verify(
                        resource,
                        budget=budget,
                        scope=intent.verification_scope,
                    )
                except ResourceVerificationFailure as exc:
                    events.append(
                        RunEvent(
                            phase="resource_verification",
                            status="failed",
                            code=exc.code,
                            detail=exc.detail or resource.locator,
                            request_kind="external",
                        )
                    )
                    self.store.record_event("resource_verification", "failed", exc.code)
                    continue
                resources[index] = verified
                self.store.save_resources([verified])
                events.append(
                    RunEvent(
                        phase="resource_verification",
                        status="checkpointed",
                        detail=verified.locator,
                        request_kind="external",
                    )
                )

        has_failures = any(event.status in {"failed", "circuit_open"} for event in events)
        has_outputs = bool(candidates or resources)
        if has_outputs and (budget.circuit_open or has_failures):
            status = "partial_success"
        elif not has_outputs:
            status = "failed"
        else:
            status = "success"

        return RunOutcome(
            status=status,
            intent=intent,
            query_plan=plan,
            budget=budget,
            candidates=ranked,
            selected_candidates=selected,
            evidence=evidence,
            resources=resources,
            events=events,
            limitations=(
                ["Bilibili circuit opened; only pre-circuit evidence was retained"]
                if budget.circuit_open
                else []
            ),
        )
