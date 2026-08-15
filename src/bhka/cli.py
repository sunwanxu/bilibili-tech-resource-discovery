from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from . import __version__
from .analyzers import DeepSeekAnalyzer, HeuristicAnalyzer, OpenAIAnalyzer
from .browser_login import BrowserLoginError, interactive_edge_login
from .config import Settings
from .discovery import (
    DiscoveryPipeline,
    aggregate_candidates,
    expand_queries,
    infer_discovery_mode,
    merge_resource_pool,
    prepare_direct_resources,
    rank_resources,
    seed_video_results,
)
from .models import DiscoveryEvent, DiscoveryReport
from .source import DataSourceError, YtDlpDataSource, normalize_bvid, select_representative_parts
from .storage import FileStorage
from .web_discovery import FirecrawlClient, FirecrawlError, discover_with_firecrawl

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bhka")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    auth_status = sub.add_parser(
        "auth-status",
        help="safely verify whether the configured Bilibili session is logged in",
    )
    auth_status.add_argument("--json", action="store_true", help="emit machine-readable safe output")
    auth_status.add_argument("--project-root", type=Path, default=Path.cwd())
    login = sub.add_parser(
        "login",
        help="open a dedicated Edge window and securely configure a local Bilibili session",
    )
    login.add_argument(
        "--timeout-minutes",
        type=int,
        default=5,
        help="time allowed for interactive login (default: 5)",
    )
    login.add_argument("--project-root", type=Path, default=Path.cwd())
    analyze = sub.add_parser("analyze", help="analyze one Bilibili BV id or URL")
    analyze.add_argument("video")
    analyze.add_argument(
        "--analyzer",
        choices=["auto", "deepseek", "openai", "heuristic"],
        default="auto",
    )
    analyze.add_argument("--comments", action="store_true", help="best effort; may be slow or require login")
    analyze.add_argument(
        "--retain-raw",
        action="store_true",
        help="persist normalized subtitle/comment evidence locally; author identifiers are removed",
    )
    analyze.add_argument(
        "--summary-json",
        action="store_true",
        help="emit only a machine-readable, content-free test summary on stdout",
    )
    analyze.add_argument("--project-root", type=Path, default=Path.cwd())
    sample = sub.add_parser("sample", help="fetch a bounded semantic sample of multipart video parts")
    sample.add_argument("video")
    sample.add_argument("--parts", type=int, default=4, help="number of representative parts (default: 4)")
    sample.add_argument("--project-root", type=Path, default=Path.cwd())
    discover = sub.add_parser(
        "discover",
        help="discover Bilibili videos and hidden resources from a natural-language need",
    )
    discover.add_argument("requirement")
    discover.add_argument(
        "--mode",
        choices=["auto", "learning", "resources"],
        default="auto",
        help="result goal (default: infer learning videos or reusable resources)",
    )
    discover.add_argument("--max-candidates", type=int, default=80)
    discover.add_argument("--deep", type=int, default=8, help="videos to inspect deeply (default: 8)")
    discover.add_argument(
        "--query",
        action="append",
        dest="planned_queries",
        help="AI-interpreted search query; repeat 1-8 times (deterministic expansion is the fallback)",
    )
    discover.add_argument(
        "--candidate-url",
        action="append",
        dest="seed_video_urls",
        help="public-web Bilibili video candidate supplied by the host AI; repeat as needed",
    )
    discover.add_argument(
        "--resource-url",
        action="append",
        dest="seed_resource_urls",
        help="public project/resource URL supplied by the host AI; repeat as needed",
    )
    discover.add_argument(
        "--web-search",
        choices=["auto", "off", "firecrawl"],
        default="auto",
        help="optional public-web provider (default: use Firecrawl when configured)",
    )
    discover.add_argument(
        "--bilibili-search",
        choices=["auto", "on", "off"],
        default="off",
        help=(
            "Bilibili internal candidate search (default: off; use on only for a bounded diagnostic)"
        ),
    )
    discover.add_argument(
        "--summary-json",
        action="store_true",
        help="emit a UTF-8 machine-readable result summary on stdout",
    )
    discover.add_argument(
        "--comments",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="inspect one bounded top-comment page (default: enabled)",
    )
    discover.add_argument("--project-root", type=Path, default=Path.cwd())
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_utf8_stdio()
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = Settings.load(args.project_root)
    source = YtDlpDataSource(settings)
    storage = FileStorage(settings.project_root)
    try:
        if args.command == "login":
            if not 1 <= args.timeout_minutes <= 15:
                raise ValueError("--timeout-minutes must be between 1 and 15")
            result = interactive_edge_login(
                settings,
                timeout_seconds=args.timeout_minutes * 60,
                progress=print,
            )
            print("Bilibili login configured locally.")
            print("isLogin: true")
            print("The Bilibili session was stored securely on this device.")
            return 0
        if args.command == "auth-status":
            try:
                auth = source.verify_auth()
            except DataSourceError as exc:
                result = {
                    "configured": True,
                    "is_login": None,
                    "status": "verification_failed",
                    "failure_category": exc.category,
                }
                if args.json:
                    print(json.dumps(result))
                else:
                    print("Bilibili login verification failed safely.")
                    print(f"Failure category: {exc.category}")
                return 1
            result = auth.model_dump(mode="json")
            if args.json:
                print(json.dumps(result))
            else:
                print(f"Configured: {auth.configured}")
                print(f"isLogin: {auth.is_login}")
                print(f"Status: {auth.status}")
            return 0 if auth.status == "valid" else 2
        if args.command == "discover":
            discovery_mode = (
                infer_discovery_mode(args.requirement)
                if args.mode == "auto"
                else args.mode
            )
            deep_limit = min(args.deep, 4) if discovery_mode == "learning" else args.deep
            include_comments = args.comments and discovery_mode == "resources"
            if not args.summary_json:
                print(f"Starting discovery with bhka {__version__}.", flush=True)
                print(f"Selected result mode: {discovery_mode}.", flush=True)
            seed_video_urls = list(args.seed_video_urls or [])
            seed_resource_urls = list(args.seed_resource_urls or [])
            public_web_events: list[DiscoveryEvent] = []
            public_web_limitations: list[str] = []
            cached_videos, cached_resources = storage.load_discovery_seeds(
                args.requirement,
                max_age_hours=settings.cache_ttl_hours,
            )
            seed_video_urls.extend(cached_videos)
            seed_resource_urls.extend(cached_resources)
            cache_sufficient = (
                len(cached_videos) >= deep_limit
                and (discovery_mode == "learning" or len(cached_resources) >= 5)
            )
            if cached_videos or cached_resources:
                public_web_events.append(DiscoveryEvent(
                    phase="local_cache",
                    status="reused",
                    detail=(
                        f"{len(cached_videos)} video candidates and "
                        f"{len(cached_resources)} resources"
                    ),
                ))
            if args.web_search == "firecrawl" and not settings.firecrawl_api_key:
                raise ValueError(
                    "FIRECRAWL_API_KEY is required for --web-search firecrawl"
                )
            if (
                args.web_search != "off"
                and settings.firecrawl_api_key
                and (not cache_sufficient or args.web_search == "firecrawl")
            ):
                if not args.summary_json:
                    print(
                        "Searching public web and open-project platforms with Firecrawl...",
                        flush=True,
                    )
                firecrawl = FirecrawlClient(
                    settings.firecrawl_api_key,
                    base_url=settings.firecrawl_base_url,
                    timeout_seconds=settings.firecrawl_timeout_seconds,
                )
                try:
                    web_progress = (
                        (lambda message: print(message, file=sys.stderr, flush=True))
                        if args.summary_json
                        else lambda message: print(message, flush=True)
                    )
                    public_web = discover_with_firecrawl(
                        firecrawl,
                        args.requirement,
                        per_query=settings.firecrawl_search_limit,
                        mode=discovery_mode,
                        progress=web_progress,
                    )
                    seed_video_urls.extend(public_web.video_urls)
                    seed_resource_urls.extend(public_web.resource_urls)
                    public_web_events.append(DiscoveryEvent(
                        phase="public_web_search",
                        status=("partial_success" if public_web.failures else "success"),
                        detail=(
                            f"Firecrawl returned {public_web.result_count} results, "
                            f"{len(public_web.video_urls)} Bilibili candidates, and "
                            f"{len(public_web.resource_urls)} direct resources"
                        ),
                    ))
                    if public_web.failures:
                        public_web_limitations.append(
                            "Some optional Firecrawl queries failed; successful public-web "
                            "results were retained."
                        )
                except FirecrawlError as exc:
                    public_web_events.append(DiscoveryEvent(
                        phase="public_web_search",
                        status="failed",
                        detail=exc.category,
                    ))
                    public_web_limitations.append(
                        "Optional Firecrawl public-web discovery failed "
                        f"({exc.category}); existing discovery continued."
                    )
                    if not args.summary_json:
                        print(
                            "Firecrawl public-web discovery was unavailable; "
                            "continuing with existing sources.",
                            flush=True,
                        )
            cooldown = storage.active_cooldown()
            if cooldown:
                queries = (
                    list(dict.fromkeys(
                        " ".join(query.split())
                        for query in args.planned_queries
                        if query.strip()
                    ))
                    if args.planned_queries
                    else expand_queries(args.requirement)
                )
                if not args.summary_json:
                    print("Bilibili requests skipped during the local safety cooldown.")
                    print(
                        "Adaptive client cooldown: "
                        f"{cooldown['cooldown_minutes']} minutes "
                        f"(strike {cooldown['consecutive_412_count']})."
                    )
                    print(f"Recommended not before: {cooldown['recommended_not_before']}")
                seeded_candidates = aggregate_candidates(seed_video_results(
                    seed_video_urls, args.requirement
                ))[:args.max_candidates]
                direct_resources = prepare_direct_resources(
                    seed_resource_urls,
                    verify=discovery_mode == "resources",
                )
                ranked_resources = rank_resources(merge_resource_pool(direct_resources))
                report = DiscoveryReport(
                    run_status=(
                        "partial_success" if seeded_candidates or direct_resources else "failed"
                    ),
                    discovery_mode=discovery_mode,
                    requirement=args.requirement,
                    expanded_queries=queries,
                    candidates_found=len(seeded_candidates),
                    deep_inspection_limit=deep_limit,
                    skipped_queries=len(queries),
                    stop_reason="cooldown_active",
                    failure_category="rate_limited",
                    candidates=seeded_candidates,
                    resources=ranked_resources,
                    direct_resources=direct_resources,
                    events=[DiscoveryEvent(
                        phase="preflight",
                        status="skipped_due_to_cooldown",
                    )],
                    evidence_limitations=[
                        (
                            "A previous HTTP 412 activated an adaptive client safety cooldown. "
                            "This is not an official Bilibili countdown and does not mean login "
                            "failed."
                        )
                    ],
                )
            else:
                pipeline = DiscoveryPipeline(source)
                report = pipeline.run(
                    args.requirement,
                    max_candidates=args.max_candidates,
                    deep_limit=deep_limit,
                    include_comments=include_comments,
                    planned_queries=args.planned_queries,
                    seed_video_urls=seed_video_urls,
                    seed_resource_urls=seed_resource_urls,
                    bilibili_search=args.bilibili_search,
                    discovery_mode=discovery_mode,
                    progress=(
                        (lambda message: print(message, file=sys.stderr, flush=True))
                        if args.summary_json
                        else lambda message: print(message, flush=True)
                    ),
                )
            report.events = [*public_web_events, *report.events]
            report.evidence_limitations.extend(public_web_limitations)
            json_path, report_path = storage.save_discovery(report)
            if args.summary_json:
                print(json.dumps({
                    "run_status": report.run_status,
                    "discovery_mode": report.discovery_mode,
                    "failure_category": report.failure_category,
                    "stop_reason": report.stop_reason,
                    "candidates_found": report.candidates_found,
                    "deep_inspection_limit": report.deep_inspection_limit,
                    "videos_inspected": len(report.videos),
                    "resources_found": len(report.resources),
                    "candidate_urls": [item.webpage_url for item in report.candidates],
                    "resource_urls": [item.locator for item in report.resources],
                    "json_path": str(json_path),
                    "report_path": str(report_path),
                }, ensure_ascii=False))
                return 1 if report.run_status == "failed" else 0
            print(f"Candidates found: {report.candidates_found}")
            print(f"Videos inspected: {len(report.videos)}")
            print(f"Usable resource findings: {len(report.resources)}")
            print(f"Run status: {report.run_status}")
            print(
                f"Queries: {report.successful_queries} successful, "
                f"{report.failed_queries} failed, {report.skipped_queries} skipped"
            )
            if report.stopped_at_query:
                print(f"Stopped at query: {report.stopped_at_query}")
            if report.stop_reason:
                print(f"Stop reason: {report.stop_reason}")
            if report.failure_category:
                print(f"Failure category: {report.failure_category}")
            print(f"JSON saved: {json_path}")
            print(f"Report saved: {report_path}")
            return 1 if report.run_status == "failed" else 0
        if args.command == "sample":
            if not 1 <= args.parts <= 8:
                raise ValueError("--parts must be between 1 and 8")
            bvid = normalize_bvid(args.video)
            print("Listing multipart directory...")
            parts = source.list_parts(args.video)
            selections = select_representative_parts(parts, args.parts)
            raw_paths = []
            for selection in selections:
                part = selection.part
                print(f"Fetching P{part.page}: {part.title} [{selection.role}]...")
                raw = source.fetch(args.video, part=part.page)
                raw_paths.append(storage.save_raw(raw))
            manifest_path = storage.save_sample_manifest(
                bvid,
                len(parts),
                selections,
                raw_paths,
            )
            print(f"Sampled {len(selections)}/{len(parts)} parts")
            print(f"Manifest saved: {manifest_path}")
            return 0
        if args.summary_json:
            # This mode is a transport/evidence smoke test. It must not depend
            # on, instantiate, or call an optional AI analyzer.
            raw = source.fetch(args.video, include_comments=args.comments)
            print(json.dumps(_analysis_summary(raw, settings), ensure_ascii=False))
            return 0
        if args.analyzer == "openai" and not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for --analyzer openai")
        if args.analyzer == "deepseek" and not settings.deepseek_api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is required for --analyzer deepseek")
        use_deepseek = args.analyzer == "deepseek" or (
            args.analyzer == "auto" and bool(settings.deepseek_api_key)
        )
        use_openai = args.analyzer == "openai" or (
            args.analyzer == "auto" and not use_deepseek and bool(settings.openai_api_key)
        )
        if use_deepseek:
            analyzer = DeepSeekAnalyzer(
                settings.deepseek_api_key,
                settings.deepseek_model,
                settings.deepseek_base_url,
            )
            analyzer_label = "DeepSeek"
        elif use_openai:
            analyzer = OpenAIAnalyzer(settings.openai_api_key, settings.openai_model)
            analyzer_label = "OpenAI"
        else:
            analyzer = HeuristicAnalyzer()
            analyzer_label = "heuristic baseline"
        print("Fetching metadata and available subtitles...")
        raw = source.fetch(args.video, include_comments=args.comments)
        raw_path = storage.save_raw(raw) if args.retain_raw else None
        print(f"Analyzing with {analyzer_label}...")
        analysis = analyzer.analyze(raw)
        json_path, report_path = storage.save_analysis(analysis)
    except (ValueError, DataSourceError, BrowserLoginError, RuntimeError) as exc:
        if args.command == "analyze" and getattr(args, "summary_json", False):
            category = exc.category if isinstance(exc, DataSourceError) else "configuration"
            print(json.dumps({
                "run_status": "failed",
                "authentication": _authentication_label(settings),
                "metadata_success": False,
                "subtitle_tracks": 0,
                "subtitle_languages": [],
                "subtitle_characters": 0,
                "comments": 0,
                "http_412": category == "rate_limited",
                "warnings": [],
                "errors": [{
                    "code": _error_code(category),
                    "category": category,
                    "severity": "error",
                }],
            }))
            return 1
        logger.error("%s", exc)
        return 1
    print(f"Technical Depth: {analysis.technical_depth.score}")
    print(f"Engineering Value: {analysis.engineering_value.score}")
    print(f"Possible Hidden Value: {analysis.possible_hidden_value.score}")
    print(f"Raw saved: {raw_path}" if raw_path else "Raw evidence not retained (use --retain-raw to opt in).")
    print(f"JSON saved: {json_path}")
    print(f"Report saved: {report_path}")
    return 0


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def _authentication_label(settings: Settings) -> str:
    if settings.cookies_file:
        managed = settings.project_root / ".auth" / "bilibili.cookies.txt"
        try:
            if settings.cookies_file.resolve() == managed.resolve():
                return "managed_configured"
        except OSError:
            pass
        return "external_cookie_file_configured"
    if settings.cookies_from_browser:
        return "browser_profile_configured"
    return "public_mode"


def _warning_code(message: str) -> tuple[str, str]:
    lowered = message.lower()
    if "412" in lowered or "precondition failed" in lowered:
        return "HTTP_412_RISK_CONTROL", "rate_limited"
    if "comment" in lowered or "reply" in lowered:
        return "COMMENTS_INCOMPLETE", "comments"
    if "subtitle" in lowered:
        return "SUBTITLES_INCOMPLETE", "subtitles"
    return "UPSTREAM_WARNING", "upstream"


def _error_code(category: str) -> str:
    return {
        "authentication": "AUTHENTICATION_FAILED",
        "rate_limited": "HTTP_412_RISK_CONTROL",
        "configuration": "CONFIGURATION_ERROR",
        "network": "NETWORK_ERROR",
    }.get(category, "UPSTREAM_ERROR")


def _analysis_summary(raw, settings: Settings) -> dict:
    warnings = []
    for message in raw.warnings:
        code, category = _warning_code(message)
        warnings.append({"code": code, "category": category, "severity": "warning"})
    return {
        "run_status": "success",
        "authentication": _authentication_label(settings),
        "metadata_success": True,
        "subtitle_tracks": len(raw.subtitles),
        "subtitle_languages": [track.language for track in raw.subtitles],
        "subtitle_characters": sum(len(track.text) for track in raw.subtitles),
        "comments": len(raw.comments),
        "http_412": any(item["code"] == "HTTP_412_RISK_CONTROL" for item in warnings),
        "warnings": warnings,
        "errors": [],
    }


if __name__ == "__main__":
    sys.exit(main())
