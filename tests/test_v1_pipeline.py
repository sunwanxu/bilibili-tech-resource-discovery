from dataclasses import dataclass, field

from bhka.v1.contracts import (
    DiscoveryCandidate,
    DiscoveryMode,
    EvidenceRecord,
    IntentProfile,
    NetworkBudget,
    QueryPlan,
    QuerySpec,
)
from bhka.v1.pipeline import PlatformCircuitBreak, V1DiscoveryPipeline


def intent() -> IntentProfile:
    return IntentProfile(
        original_request="寻找 STM32 PCB 开源资料",
        goal="找到可直接参考的 PCB 项目",
        mode=DiscoveryMode.RESOURCE,
    )


class Planner:
    def __init__(self, candidate_target: int = 20):
        self.candidate_target = candidate_target

    def plan(self, _intent):
        return QueryPlan(
            queries=[
                QuerySpec(text="first", purpose="precise"),
                QuerySpec(text="second", purpose="expand"),
            ],
            candidate_target=self.candidate_target,
            selected_target=3,
            deep_read_target=2,
        )


class Ranker:
    def rank(self, _intent, candidates):
        return sorted(candidates, key=lambda item: item.canonical_id)


@dataclass
class Store:
    cached: list[DiscoveryCandidate] = field(default_factory=list)
    candidate_checkpoints: int = 0
    evidence_checkpoints: int = 0
    recorded_events: list[tuple[str, str, str | None]] = field(default_factory=list)

    def load_candidates(self, _intent):
        return list(self.cached)

    def save_candidates(self, candidates):
        self.cached = list(candidates)
        self.candidate_checkpoints += 1

    def save_evidence(self, evidence):
        self.evidence_checkpoints += 1

    def record_event(self, phase, status, code=None):
        self.recorded_events.append((phase, status, code))


class CircuitDiscoverer:
    calls = 0

    def discover(self, query, *, budget):
        self.calls += 1
        if query.text == "second":
            raise PlatformCircuitBreak("http_412")
        return [
            DiscoveryCandidate(
                canonical_id="BV1",
                url="https://www.bilibili.com/video/BV1",
                title="candidate",
                provenance=["bilibili_search_page"],
                matched_queries=[query.text],
            )
        ]


class Reader:
    def __init__(self):
        self.calls = 0

    def read(self, candidate, *, budget, include_comments):
        self.calls += 1
        return [
            EvidenceRecord(
                evidence_id=f"e-{candidate.canonical_id}",
                subject_id=candidate.canonical_id,
                source_kind="description",
                source_url=candidate.url,
            )
        ]


def test_412_during_search_stops_all_deep_reads_and_keeps_candidates():
    reader = Reader()
    store = Store()
    pipeline = V1DiscoveryPipeline(
        planner=Planner(),
        discoverer=CircuitDiscoverer(),
        ranker=Ranker(),
        reader=reader,
        store=store,
    )

    result = pipeline.run(intent(), budget=NetworkBudget())

    assert result.status == "partial_success"
    assert [item.canonical_id for item in result.candidates] == ["BV1"]
    assert reader.calls == 0
    assert result.budget.circuit_reason == "http_412"
    assert any(event.phase == "deep_read" and event.status == "skipped" for event in result.events)


class EnoughDiscoverer:
    def __init__(self):
        self.calls = 0

    def discover(self, query, *, budget):
        self.calls += 1
        return [
            DiscoveryCandidate(
                canonical_id=f"BV{index}",
                url=f"https://www.bilibili.com/video/BV{index}",
                provenance=["bilibili_search_page"],
                matched_queries=[query.text],
            )
            for index in range(5)
        ]


def test_candidate_target_stops_followup_query_and_checkpoints_each_deep_read():
    discoverer = EnoughDiscoverer()
    reader = Reader()
    store = Store()
    pipeline = V1DiscoveryPipeline(
        planner=Planner(candidate_target=5),
        discoverer=discoverer,
        ranker=Ranker(),
        reader=reader,
        store=store,
    )

    result = pipeline.run(intent(), budget=NetworkBudget())

    assert result.status == "success"
    assert discoverer.calls == 1
    assert reader.calls == 2
    assert store.evidence_checkpoints == 2
    assert any(event.code == "candidate_target_reached" for event in result.events)

