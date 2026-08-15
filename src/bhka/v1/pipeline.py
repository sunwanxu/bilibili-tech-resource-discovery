from __future__ import annotations

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
)
from .ports import CandidateDiscoverer, CandidateRanker, CheckpointStore, EvidenceReader


class PlatformCircuitBreak(RuntimeError):
    """A deterministic upstream signal after which no new Bilibili request is allowed."""

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

    def run(self, intent: IntentProfile, *, budget: NetworkBudget) -> RunOutcome:
        plan = self.planner.plan(intent)
        events: list[RunEvent] = []
        candidates = self.store.load_candidates(intent)
        if candidates:
            events.append(
                RunEvent(
                    phase="discovery",
                    status="cache_hit",
                    detail=f"Loaded {len(candidates)} cached candidates",
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
            candidates = merge_candidates(candidates, found)
            self.store.save_candidates(candidates)
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
        evidence: list[EvidenceRecord] = []

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

        if candidates and budget.circuit_open:
            status = "partial_success"
        elif not candidates:
            status = "failed"
        else:
            status = "success"

        return RunOutcome(
            status=status,
            intent=intent,
            query_plan=plan,
            budget=budget,
            candidates=selected,
            evidence=evidence,
            events=events,
            limitations=(
                ["Bilibili circuit opened; only pre-circuit evidence was retained"]
                if budget.circuit_open
                else []
            ),
        )

