from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from bhka.config import Settings
from bhka.source import YtDlpDataSource

from .cache import SQLiteCheckpointStore
from .contracts import (
    Breadth,
    DiscoveryMode,
    IntentProfile,
    NetworkBudget,
    RunEvent,
    RunOutcome,
    VerificationScope,
)
from .evidence_reader import YtDlpEvidenceReader
from .pipeline import V1DiscoveryPipeline
from .planner import StableQueryPlanner
from .ranking import DeterministicCandidateRanker
from .reporting import ReportWriter
from .resource_extraction import EvidenceResourceExtractor
from .resource_verification import GitHubResourceVerifier, ResourceVerifierRouter
from .search_session import (
    BilibiliSearchPageDiscoverer,
    ManagedEdgeSearchSession,
    SearchSessionError,
)

_LEARNING_MARKERS = ("学习", "想学", "教程", "入门", "从零", "课程", "怎么画", "怎么做")
_RESOURCE_MARKERS = ("开源", "源码", "代码", "工程", "资料", "设计方案", "复刻")


def infer_mode(request: str) -> DiscoveryMode | None:
    lowered = request.casefold()
    learning = any(marker.casefold() in lowered for marker in _LEARNING_MARKERS)
    resource = any(marker.casefold() in lowered for marker in _RESOURCE_MARKERS)
    if learning and resource:
        return None
    if learning:
        return DiscoveryMode.LEARNING
    return DiscoveryMode.RESOURCE


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bhka-v1",
        description="Draft v1 Bilibili technical-video and resource discovery engine",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    discover = subparsers.add_parser("discover", help="Search from one natural-language need")
    discover.add_argument("request")
    discover.add_argument("--goal")
    discover.add_argument("--level")
    discover.add_argument("--constraint", action="append", default=[])
    discover.add_argument("--mode", choices=["auto", "learning", "resource"], default="auto")
    discover.add_argument("--breadth", choices=[item.value for item in Breadth], default="standard")
    discover.add_argument("--verification", choices=[item.value for item in VerificationScope], default="core")
    discover.add_argument("--query", action="append", default=[])
    discover.add_argument("--deep-read", type=int, choices=range(16))
    discover.add_argument("--bilibili-budget", type=int, default=10)
    discover.add_argument("--external-budget", type=int, default=12)
    discover.add_argument("--visible-browser", action=argparse.BooleanOptionalAction, default=True)
    discover.add_argument("--project-root", type=Path, default=Path.cwd())
    return parser


def _summary(outcome: RunOutcome, paths) -> dict[str, object]:
    return {
        "ok": outcome.status != "failed",
        "schema_version": outcome.schema_version,
        "run_id": outcome.run_id,
        "status": outcome.status,
        "counts": {
            "candidates": len(outcome.candidates),
            "selected": len(outcome.selected_candidates),
            "evidence": len(outcome.evidence),
            "resources": len(outcome.resources),
        },
        "budget": outcome.budget.model_dump(),
        "paths": {
            "json": str(paths.json_path),
            "markdown": str(paths.markdown_path),
            "latest_json": str(paths.latest_json_path),
        },
    }


def _intent_from_args(args: argparse.Namespace) -> IntentProfile | None:
    mode = infer_mode(args.request) if args.mode == "auto" else DiscoveryMode(args.mode)
    if mode is None:
        return None
    return IntentProfile(
        original_request=args.request,
        goal=args.goal or args.request,
        mode=mode,
        user_level=args.level,
        constraints=args.constraint,
        breadth=Breadth(args.breadth),
        verification_scope=VerificationScope(args.verification),
    )


def run_discover(args: argparse.Namespace) -> int:
    intent = _intent_from_args(args)
    if intent is None:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": "mode_clarification_required",
                        "message": "请先确认更重视学习视频，还是开源资料。",
                    },
                },
                ensure_ascii=False,
            )
        )
        return 2
    root = args.project_root.resolve()
    settings = Settings.load(root)
    planner = StableQueryPlanner(
        explicit_queries=args.query,
        deep_read_target=args.deep_read,
    )
    plan = planner.plan(intent)
    budget = NetworkBudget(
        bilibili_requests_limit=args.bilibili_budget,
        external_requests_limit=args.external_budget,
    )
    store = SQLiteCheckpointStore(root / "data" / "v1" / "cache.sqlite3")
    writer = ReportWriter(root / "reports" / "v1")
    try:
        with ManagedEdgeSearchSession(
            root / ".auth" / "v1-edge-profile",
            visible=args.visible_browser,
        ) as session:
            pipeline = V1DiscoveryPipeline(
                planner=planner,
                discoverer=BilibiliSearchPageDiscoverer(session),
                ranker=DeterministicCandidateRanker(),
                reader=YtDlpEvidenceReader(YtDlpDataSource(settings)),
                store=store,
                resource_extractor=EvidenceResourceExtractor(),
                resource_verifier=ResourceVerifierRouter(
                    github=GitHubResourceVerifier(token=os.getenv("GITHUB_TOKEN"))
                ),
            )
            outcome = pipeline.run(intent, budget=budget)
    except SearchSessionError as exc:
        outcome = RunOutcome(
            status="failed",
            intent=intent,
            query_plan=plan,
            budget=budget,
            events=[
                RunEvent(
                    phase="session",
                    status="failed",
                    code="managed_edge_unavailable",
                    detail=str(exc),
                )
            ],
            limitations=[str(exc)],
        )
    paths = writer.write(outcome)
    print(json.dumps(_summary(outcome, paths), ensure_ascii=False))
    return 0 if outcome.status != "failed" else 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "discover":
        return run_discover(args)
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
