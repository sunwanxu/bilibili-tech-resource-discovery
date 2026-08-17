import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import bhka.cli as cli_module
import bhka.discovery as discovery_module
from bhka.analyzers import HeuristicAnalyzer
from bhka.discovery import (
    DiscoveryPipeline,
    aggregate_candidates,
    classify_open_source,
    expand_queries,
    extract_resources,
    infer_discovery_mode,
    infer_repository_artifacts,
    inspect_external_resources,
    merge_resource_pool,
    passes_hard_relevance,
    prepare_direct_resources,
    rank_resources,
    seed_video_results,
)
from bhka.models import (
    Comment,
    DiscoveredVideo,
    DiscoveryReport,
    ExternalResource,
    RawVideoData,
    SearchCandidate,
    SearchResult,
    SubtitleTrack,
    VideoMetadata,
    VideoPart,
)
from bhka.source import (
    DataSourceError,
    YtDlpDataSource,
    browser_cookie_spec,
    normalize_bvid,
    normalize_video_id,
    select_representative_parts,
)
from bhka.storage import FileStorage, render_discovery_markdown


def sample_raw() -> RawVideoData:
    return RawVideoData(
        fetched_at=datetime.now(UTC),
        source="test",
        metadata=VideoMetadata(
            bvid="BV1234567890",
            title="STM32 PID 电机实测",
            description="包含 GitHub 源码、编码器、PWM 和踩坑调试",
            views=4200,
            likes=100,
            webpage_url="https://www.bilibili.com/video/BV1234567890",
        ),
        subtitles=[SubtitleTrack(language="zh", text="使用示波器调试 UART 和 DMA")],
    )


def test_normalize_bvid_accepts_url_and_id():
    assert normalize_bvid("BV1234567890") == "BV1234567890"
    assert normalize_bvid("https://www.bilibili.com/video/BV1234567890?p=1") == "BV1234567890"
    with pytest.raises(ValueError):
        normalize_bvid("not-a-video")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("116136268144356", "av116136268144356"),
        ("av116136268144356", "av116136268144356"),
        ("https://www.bilibili.com/video/116136268144356", "av116136268144356"),
        ("https://www.bilibili.com/video/av116136268144356", "av116136268144356"),
        ("BV1234567890", "BV1234567890"),
    ],
)
def test_normalize_video_id_accepts_numeric_aid_and_canonical_ids(value: str, expected: str):
    assert normalize_video_id(value) == expected


def test_search_results_expose_analyze_compatible_canonical_ids(monkeypatch, tmp_path: Path):
    class FakeYoutubeDL:
        def __init__(self, options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            return {"entries": [{
                "id": "116136268144356",
                "url": "116136268144356",
                "title": "FOC motor controller source walkthrough",
            }]}

    monkeypatch.setattr("bhka.source.YoutubeDL", FakeYoutubeDL)
    settings = SimpleNamespace(
        project_root=tmp_path,
        cookies_file=None,
        cookies_from_browser=None,
        bilibili_user_agent=None,
        timeout_seconds=20,
        retries=1,
        rate_limit_seconds=0,
    )

    result = YtDlpDataSource(settings).search("motor", 5)[0]

    assert result.source_id == "av116136268144356"
    assert result.webpage_url.endswith("/av116136268144356")
    assert result.title == "FOC motor controller source walkthrough"


def test_repeated_internal_search_uses_local_cache(monkeypatch, tmp_path: Path):
    calls = 0

    class FakeYoutubeDL:
        def __init__(self, options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            nonlocal calls
            calls += 1
            return {"entries": [{"id": "116136268144356"}]}

    monkeypatch.setattr("bhka.source.YoutubeDL", FakeYoutubeDL)
    settings = SimpleNamespace(
        project_root=tmp_path,
        cookies_file=None,
        cookies_from_browser=None,
        bilibili_user_agent=None,
        timeout_seconds=20,
        retries=1,
        rate_limit_seconds=0,
        cache_ttl_hours=168,
    )

    first = YtDlpDataSource(settings).search("motor", 5)
    second = YtDlpDataSource(settings).search("motor", 5)

    assert calls == 1
    assert second == first


def test_invalid_ipv6_url_from_extractor_becomes_a_bounded_source_error(
    monkeypatch,
    tmp_path: Path,
):
    class FakeYoutubeDL:
        def __init__(self, options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            raise ValueError("Invalid IPv6 URL")

    monkeypatch.setattr("bhka.source.YoutubeDL", FakeYoutubeDL)
    settings = SimpleNamespace(
        project_root=tmp_path,
        cookies_file=None,
        cookies_from_browser=None,
        bilibili_user_agent=None,
        timeout_seconds=20,
        retries=1,
        rate_limit_seconds=0,
        cache_ttl_hours=168,
    )

    with pytest.raises(DataSourceError) as captured:
        YtDlpDataSource(settings).search("motor", 5)

    assert captured.value.category == "upstream"
    assert "Invalid IPv6 URL" in str(captured.value)


def test_repeated_video_fetch_reuses_cached_metadata_and_subtitles(
    monkeypatch,
    tmp_path: Path,
):
    calls = 0

    class FakeYoutubeDL:
        def __init__(self, options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            nonlocal calls
            calls += 1
            return {
                "id": "BV1234567890",
                "display_id": "BV1234567890",
                "webpage_url": "https://www.bilibili.com/video/BV1234567890",
                "title": "cached motor tutorial",
                "description": "github.com/example/project",
                "subtitles": {},
                "automatic_captions": {},
            }

    monkeypatch.setattr("bhka.source.YoutubeDL", FakeYoutubeDL)
    settings = SimpleNamespace(
        project_root=tmp_path,
        cookies_file=None,
        cookies_from_browser=None,
        bilibili_user_agent=None,
        timeout_seconds=20,
        retries=1,
        rate_limit_seconds=0,
        cache_ttl_hours=168,
    )

    first = YtDlpDataSource(settings).fetch("BV1234567890")
    second = YtDlpDataSource(settings).fetch("BV1234567890")

    assert calls == 1
    assert second.metadata.title == first.metadata.title
    assert second.metadata.author is None


def test_browser_cookie_spec_is_explicit_and_validated():
    assert browser_cookie_spec("chrome") == ("chrome",)
    assert browser_cookie_spec("chrome:Profile 1") == ("chrome", "Profile 1", None, None)
    with pytest.raises(ValueError):
        browser_cookie_spec("unknown-browser")


def test_bounded_comment_parser_flattens_replies_and_honors_limit():
    payload = {
        "data": {
            "replies": [{
                "member": {"uname": "alice"},
                "content": {"message": "root"},
                "like": 3,
                "ctime": 1_700_000_000,
                "replies": [{
                    "member": {"uname": "bob"},
                    "content": {"message": "child"},
                    "like": 1,
                    "ctime": 1_700_000_001,
                }],
            }, {
                "member": {"uname": "carol"},
                "content": {"message": "not included"},
            }],
        },
    }

    comments = YtDlpDataSource._parse_bilibili_comments(payload, limit=2)

    assert [comment.author for comment in comments] == ["alice", "bob"]
    assert [comment.text for comment in comments] == ["root", "child"]


def test_heuristic_output_validates_and_preserves_dimensions():
    result = HeuristicAnalyzer().analyze(sample_raw())
    assert result.analysis_method == "heuristic_baseline"
    assert result.engineering_value.score >= 5
    assert result.possible_hidden_value.reason


def test_storage_writes_raw_json_and_markdown(tmp_path: Path):
    raw = sample_raw()
    raw.metadata.author = "public-uploader-id"
    raw.comments = [Comment(author="commenter-id", text="useful link")]
    storage = FileStorage(tmp_path)
    raw_path = storage.save_raw(raw)
    json_path, report_path = storage.save_analysis(HeuristicAnalyzer().analyze(raw))
    assert raw_path.exists() and json_path.exists() and report_path.exists()
    assert "STM32 PID" in report_path.read_text(encoding="utf-8")
    persisted = json.loads(raw_path.read_text(encoding="utf-8"))
    assert "author" not in persisted["metadata"]
    assert "author" not in persisted["comments"][0]
    assert "extractor_info" not in persisted


def test_analysis_summary_is_content_free_and_machine_readable(tmp_path: Path):
    raw = sample_raw()
    raw.comments = [Comment(author="private-name", text="private comment")]
    raw.warnings = ["Bounded comment fetch failed"]
    settings = SimpleNamespace(
        project_root=tmp_path,
        cookies_file=tmp_path / ".auth" / "bilibili.cookies.txt",
        cookies_from_browser=None,
    )

    summary = cli_module._analysis_summary(raw, settings)

    serialized = json.dumps(summary)
    assert summary["authentication"] == "managed_configured"
    assert summary["subtitle_tracks"] == 1
    assert summary["comments"] == 1
    assert summary["warnings"][0]["code"] == "COMMENTS_INCOMPLETE"
    assert "private-name" not in serialized
    assert "private comment" not in serialized


def test_cli_exposes_runtime_version(capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli_module.main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == "bhka 1.1.0"


def test_discover_defaults_use_broad_hybrid_candidate_discovery():
    args = cli_module.build_parser().parse_args(["discover", "ESP32 project"])

    assert args.max_candidates == 80
    assert args.deep == 8
    assert args.bilibili_search == "auto"
    assert args.mode == "auto"


def test_discover_accepts_explicit_internal_search_disable():
    args = cli_module.build_parser().parse_args([
        "discover",
        "ESP32 project",
        "--bilibili-search",
        "off",
    ])

    assert args.bilibili_search == "off"


def test_auto_internal_search_runs_at_most_three_queries():
    class EmptySource:
        def __init__(self):
            self.settings = SimpleNamespace(
                cookies_file=None,
                cookies_from_browser=None,
                rate_limit_seconds=0,
            )
            self.calls = 0

        def search(self, _query, _limit):
            self.calls += 1
            return []

    source = EmptySource()
    report = DiscoveryPipeline(source).run(
        "STM32F103C8T6 PCB 开源资料",
        max_candidates=20,
        deep_limit=2,
        include_comments=False,
    )

    assert source.calls == 3
    assert report.successful_queries == 3
    assert report.skipped_queries == len(report.expanded_queries) - 3
    assert report.stop_reason == "bounded_auto_fallback_completed"


def test_discover_summary_json_is_clean_utf8_machine_output(tmp_path: Path, capsys):
    exit_code = cli_module.main([
        "discover",
        "中文缓存测试",
        "--web-search",
        "off",
        "--bilibili-search",
        "off",
        "--summary-json",
        "--project-root",
        str(tmp_path),
    ])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["run_status"] == "failed"
    assert payload["discovery_mode"] == "resources"
    assert payload["candidate_urls"] == []
    assert "中文缓存测试" in payload["json_path"]


def test_discover_auto_selects_light_learning_mode(tmp_path: Path, capsys):
    exit_code = cli_module.main([
        "discover",
        "我想学习一下AI短剧，我该看哪些视频",
        "--web-search",
        "off",
        "--bilibili-search",
        "off",
        "--summary-json",
        "--project-root",
        str(tmp_path),
    ])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 1
    assert payload["discovery_mode"] == "learning"
    assert payload["deep_inspection_limit"] == 4


def test_summary_json_never_instantiates_optional_ai_analyzer(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    settings = SimpleNamespace(
        project_root=tmp_path,
        cookies_file=None,
        cookies_from_browser=None,
        deepseek_api_key="configured-but-unused",
        openai_api_key=None,
    )

    class SummarySource:
        def __init__(self, configured_settings):
            self.settings = configured_settings

        def fetch(self, video, include_comments=False):
            return sample_raw()

    class ForbiddenAnalyzer:
        def __init__(self, *args, **kwargs):
            raise AssertionError("summary-json must not construct an AI analyzer")

    monkeypatch.setattr(cli_module.Settings, "load", lambda root: settings)
    monkeypatch.setattr(cli_module, "YtDlpDataSource", SummarySource)
    monkeypatch.setattr(cli_module, "DeepSeekAnalyzer", ForbiddenAnalyzer)

    exit_code = cli_module.main([
        "analyze",
        "116136268144356",
        "--summary-json",
        "--project-root",
        str(tmp_path),
    ])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["run_status"] == "success"


def test_select_representative_parts_uses_semantic_roles():
    titles = [
        "课程介绍",
        "STM32内部结构",
        "工程创建",
        "GPIO介绍",
        "I2C通信协议",
        "串口实验",
    ]
    parts = [
        VideoPart(
            bvid="BV1234567890",
            page=index,
            cid=100 + index,
            title=title,
            webpage_url=f"https://www.bilibili.com/video/BV1234567890?p={index}",
        )
        for index, title in enumerate(titles, 1)
    ]

    selected = select_representative_parts(parts, limit=4)

    assert [item.role for item in selected] == [
        "introduction",
        "foundation",
        "peripheral",
        "practical",
    ]
    assert len({item.part.page for item in selected}) == 4


def test_storage_keeps_part_raw_data_separate(tmp_path: Path):
    raw = sample_raw()
    raw.metadata.part_number = 7

    path = FileStorage(tmp_path).save_raw(raw)

    assert path == tmp_path / "data" / "raw_parts" / "BV1234567890" / "p007.json"
    assert path.exists()


def test_expand_queries_adds_domain_and_resource_intents():
    queries = expand_queries("我完全不会PCB，想用嘉立创EDA画STM32最小系统板")

    assert queries[0] == "嘉立创EDA STM32 最小系统 PCB"
    assert any("开源" in query for query in queries)
    assert any("GitHub" in query for query in queries)


def test_expand_queries_preserves_competition_year_problem_and_resource_intents():
    queries = expand_queries("2026 电赛 H题 开源代码 设计方案 不同技术路线 项目资料")

    assert queries[0] == "2026 电赛 H题"
    assert all("2026 电赛 H题" in query for query in queries)
    assert any("GitHub" in query for query in queries)
    assert any("Gitee" in query for query in queries)
    assert any("项目资料" in query for query in queries)
    assert len(queries) == len(set(queries))


def test_expand_queries_preserves_k_problem_and_vehicle_anchor():
    queries = expand_queries("2025 电赛 K题 小车 开源代码")

    assert queries[0] == "2025 电赛 K题 小车"
    assert all("K题" in query and "小车" in query for query in queries)


@pytest.mark.parametrize(
    ("requirement", "expected"),
    [
        ("我想学习一下AI短剧，我该看哪些视频", "learning"),
        ("完全不会画PCB，找适合零基础的教程视频", "learning"),
        ("2026 电赛 H题 开源代码和设计方案", "resources"),
        ("帮我找ESP32工程文件、原理图和GitHub仓库", "resources"),
    ],
)
def test_discovery_mode_is_inferred_from_result_goal(requirement: str, expected: str):
    assert infer_discovery_mode(requirement) == expected


@pytest.mark.parametrize(
    ("requirement", "expected_terms"),
    [
        ("ESP32-C3 MQTT 智能家居 开源代码", ["ESP32-C3", "MQTT", "智能家居"]),
        ("FastAPI Python 异步接口 中文教程", ["FastAPI", "Python", "异步接口", "中文教程"]),
        ("射频 功率放大器 ADS 仿真 设计方案", ["射频", "功率放大器", "ADS", "仿真"]),
        ("嘉立创EDA STM32 最小系统 PCB 项目资料", ["嘉立创EDA", "STM32", "最小系统", "PCB"]),
    ],
)
def test_query_expansion_preserves_entities_across_technical_domains(
    requirement: str,
    expected_terms: list[str],
):
    first_query = expand_queries(requirement)[0]

    assert all(term in first_query for term in expected_terms)


def test_generic_hard_filter_rejects_cross_domain_results_and_wrong_year():
    requirement = "2025 电赛 K题 小车"

    assert passes_hard_relevance(
        "2025 TI杯电赛K题小车完整方案",
        "智能车底盘与循迹控制",
        requirement,
    )
    assert not passes_hard_relevance(
        "2025 电子游戏比赛复盘",
        "与电子设计竞赛无关的内容",
        requirement,
    )
    assert not passes_hard_relevance(
        "2024 TI杯电赛K题小车",
        "智能车底盘",
        requirement,
    )


def test_generic_filter_does_not_require_every_model_and_acronym():
    assert passes_hard_relevance(
        "FOC 无刷电机控制入门与实测",
        "包含电流环和速度环设计",
        "无刷电机 FOC STM32 AS5600 开源代码",
    )
    assert not passes_hard_relevance(
        "Python Web 接口开发",
        "数据库与异步服务教程",
        "无刷电机 FOC STM32 AS5600 开源代码",
    )


def test_aggregate_candidates_deduplicates_and_rewards_cross_query_hits():
    results = [
        SearchResult(
            source_id="1",
            webpage_url="https://example/1",
            query="a",
            rank=3,
            title="Complete STM32 PCB project",
        ),
        SearchResult(source_id="1", webpage_url="https://example/1", query="b", rank=5),
        SearchResult(source_id="2", webpage_url="https://example/2", query="a", rank=1),
    ]

    candidates = aggregate_candidates(results)

    assert [candidate.source_id for candidate in candidates] == ["1", "2"]
    assert candidates[0].matched_queries == ["a", "b"]
    assert candidates[0].title == "Complete STM32 PCB project"


def test_public_web_video_candidates_are_normalized_deduplicated_and_attributed():
    results = seed_video_results(
        [
            "https://www.bilibili.com/video/BV1234567890",
            "BV1234567890",
            "https://example.com/not-a-video",
        ],
        "find a project",
    )

    assert len(results) == 1
    assert results[0].source_id == "BV1234567890"
    assert results[0].provenance == "web_index"
    assert aggregate_candidates(results)[0].provenance == ["web_index"]


def test_direct_public_resources_are_preserved_independently(monkeypatch):
    monkeypatch.setattr(discovery_module, "inspect_external_resources", lambda resources: resources)

    resources = prepare_direct_resources([
        "https://github.com/example/board",
        "https://github.com/example/board",
        "not-a-url",
    ])

    assert len(resources) == 1
    assert resources[0].kind == "code_repository"
    assert resources[0].origin == "public_web_direct"


def test_learning_mode_can_preserve_resource_leads_without_network_verification(monkeypatch):
    def fail_if_called(_resources):
        raise AssertionError("learning mode must not verify repositories")

    monkeypatch.setattr(discovery_module, "inspect_external_resources", fail_if_called)

    resources = prepare_direct_resources(
        ["https://github.com/example/course-assets"],
        verify=False,
    )

    assert resources[0].inspection_status == "not_inspected"


def test_resource_extraction_preserves_origin_and_access_boundary():
    raw = sample_raw()
    raw.metadata.description = "工程：https://github.com/example/board"
    raw.comments = [Comment(text="资料群：123456789，网盘 https://pan.baidu.com/s/demo")]

    resources = extract_resources(raw)

    assert [(item.kind, item.origin) for item in resources] == [
        ("code_repository", "description"),
        ("cloud_drive", "comment"),
        ("community_group", "comment"),
    ]


def test_resource_extraction_accepts_repository_links_without_scheme():
    raw = sample_raw()
    raw.metadata.description = "源码 github.com/example/board，备份 gitee.com/example/board"

    resources = extract_resources(raw)

    assert [item.locator for item in resources] == [
        "https://github.com/example/board",
        "https://gitee.com/example/board",
    ]
    assert all(item.supporting_videos == [raw.metadata.webpage_url] for item in resources)


def test_resource_pool_merges_origins_and_supporting_videos():
    direct = ExternalResource(
        locator="https://github.com/example/board",
        kind="code_repository",
        origin="public_web_direct",
        access_status="public_page",
        license_status="unverified",
        origins=["public_web_direct"],
    )
    from_video = ExternalResource(
        locator="https://github.com/example/board/",
        kind="code_repository",
        origin="comment",
        access_status="public_page",
        license_status="verified_github_spdx:MIT",
        origins=["comment"],
        supporting_videos=["https://www.bilibili.com/video/BV1234567890"],
    )

    merged = merge_resource_pool([direct], [from_video])

    assert len(merged) == 1
    assert merged[0].license_status == "verified_github_spdx:MIT"
    assert merged[0].origins == ["public_web_direct", "comment"]
    assert len(merged[0].supporting_videos) == 1


def test_resource_ranking_prefers_usable_licensed_projects_over_shared_files():
    repository = ExternalResource(
        locator="https://github.com/example/board",
        kind="code_repository",
        origin="description",
        access_status="public_page",
        license_status="verified_github_spdx:MIT",
        inspection_status="inspected",
        artifacts={"source_code": "present", "documentation": "present"},
    )
    cloud = ExternalResource(
        locator="https://pan.baidu.com/s/example",
        kind="cloud_drive",
        origin="comment",
        access_status="login_or_app_may_be_required",
        license_status="unverified",
    )

    ranked = rank_resources([cloud, repository])

    assert ranked[0].locator == repository.locator
    assert ranked[0].usability_status == "usable_open_source_verified"
    assert ranked[0].resource_score > ranked[1].resource_score


def test_open_source_promise_is_not_treated_as_open_source():
    raw = sample_raw()
    raw.metadata.description = "等板子测试完成后会开源"

    status, _ = classify_open_source(raw, [])

    assert status == "promised_open_source_link_missing"


def test_component_license_does_not_cover_unverified_complete_package():
    raw = sample_raw()
    resources = [
        ExternalResource(
            locator="https://github.com/example/qdrive",
            kind="code_repository",
            origin="description",
            access_status="public_page",
            license_status="verified_github_spdx:GPL-2.0",
        ),
        ExternalResource(
            locator="https://pan.baidu.com/s/complete-package",
            kind="cloud_drive",
            origin="description",
            access_status="login_or_app_may_be_required",
            license_status="unverified",
        ),
    ]

    status, reason = classify_open_source(raw, resources)

    assert status == "license_scope_incomplete"
    assert "only part" in reason


def test_public_repository_stays_license_unverified_without_license_evidence():
    raw = sample_raw()
    raw.metadata.description = "工程：https://github.com/example/board"
    resources = extract_resources(raw)

    status, _ = classify_open_source(raw, resources)

    assert status == "public_repository_license_unverified"


def test_generic_hard_anchor_rejects_wrong_model_family():
    requirement = "用嘉立创EDA画STM32最小系统板"

    assert passes_hard_relevance("STM32最小系统PCB全流程", "开源工程", requirement)
    assert not passes_hard_relevance("ESP32最小系统PCB全流程", "开源工程", requirement)


def test_repository_artifact_inference_uses_evidence_not_assumptions():
    artifacts = infer_repository_artifacts([
        "hardware/board.kicad_sch",
        "hardware/board.kicad_pcb",
        "manufacturing/BOM.csv",
        "manufacturing/gerber.zip",
        "firmware/main.c",
        "README.md",
    ], readme="实物已经焊接验证。")

    assert artifacts == {
        "schematic": "present",
        "pcb": "present",
        "bom": "present",
        "gerber": "present",
        "source_code": "present",
        "documentation": "present",
        "hardware_validation": "present",
    }


def test_login_resource_is_left_for_human_review():
    raw = sample_raw()
    raw.metadata.description = "资料：https://pan.baidu.com/s/demo"
    resources = extract_resources(raw)

    inspect_external_resources(resources)

    assert resources[0].inspection_status == "blocked_or_human_review_required"
    assert resources[0].artifacts == {}


def test_resource_inspection_follows_supported_nested_links(monkeypatch):
    resource = discovery_module.ExternalResource(
        locator="https://oshwhub.com/example/project",
        kind="hardware_project",
        origin="description",
        access_status="public_page_clone_may_require_login",
        license_status="unverified",
    )

    def fake_oshwhub(item, timeout):
        item.inspection_status = "inspected"
        return ["https://github.com/example/project"]

    def fake_github(item, parts, timeout):
        item.inspection_status = "inspected"
        item.license_status = "verified_github_spdx:MIT"
        return []

    monkeypatch.setattr(discovery_module, "_inspect_oshwhub", fake_oshwhub)
    monkeypatch.setattr(discovery_module, "_inspect_github", fake_github)

    resources = [resource]
    inspect_external_resources(resources)

    assert [item.kind for item in resources] == ["hardware_project", "code_repository"]
    assert resources[1].origin == "nested_from:hardware_project"
    assert resources[1].license_status == "verified_github_spdx:MIT"


def test_discovery_report_renders_artifact_completeness():
    resource = ExternalResource(
        locator="https://github.com/example/board",
        kind="code_repository",
        origin="description",
        access_status="public_page",
        license_status="verified_github_spdx:MIT",
        inspection_status="inspected",
        artifacts={"schematic": "present", "bom": "not_evidenced"},
    )
    report = DiscoveryReport(
        requirement="find a board",
        expanded_queries=["board open source"],
        candidates_found=1,
        deep_inspection_limit=1,
        resources=rank_resources([resource.model_copy(deep=True)]),
        videos=[DiscoveredVideo(
            bvid="BV1234567890",
            title="board",
            webpage_url="https://www.bilibili.com/video/BV1234567890",
            discovery_score=1,
            suitability_score=8,
            suitability_reason="matching project",
            open_source_status="explicit_license_verified",
            open_source_reason="MIT",
            resources=[resource],
        )],
    )

    markdown = render_discovery_markdown(report)

    assert "schematic=present" in markdown
    assert "bom=not_evidenced" in markdown
    assert markdown.index("Primary usable project resources") < markdown.index(
        "Supporting Bilibili videos"
    )


class FailingSearchSource:
    def __init__(self, failures: list[DataSourceError | None]):
        self.settings = SimpleNamespace(
            cookies_file=None,
            cookies_from_browser=None,
            rate_limit_seconds=0,
        )
        self.failures = failures
        self.calls = 0

    def search(self, query: str, limit: int):
        failure = self.failures[min(self.calls, len(self.failures) - 1)]
        self.calls += 1
        if failure:
            raise failure
        return []


class FailingAuthPreflightSource:
    def __init__(self):
        self.settings = SimpleNamespace(
            cookies_file=None,
            cookies_from_browser="edge",
            rate_limit_seconds=0,
        )
        self.search_calls = 0
        self.preview_calls = 0

    def verify_auth(self):
        raise DataSourceError(
            "Configured browser: edge. Windows could not decrypt cookies.",
            category="authentication",
            deterministic=True,
        )

    def search(self, query: str, limit: int):
        self.search_calls += 1
        return []


class CircuitAfterCandidateSource:
    def __init__(self):
        self.settings = SimpleNamespace(
            cookies_file=None,
            cookies_from_browser=None,
            rate_limit_seconds=0,
        )
        self.search_calls = 0
        self.preview_calls = 0
        self.fetch_calls = 0

    def search(self, query: str, limit: int):
        self.search_calls += 1
        if self.search_calls == 1:
            return [SearchResult(
                source_id="BV1234567890",
                webpage_url="https://www.bilibili.com/video/BV1234567890",
                query=query,
                rank=1,
            )]
        raise DataSourceError(
            "HTTP 412",
            category="rate_limited",
            deterministic=True,
        )

    def preview(self, video: str):
        self.preview_calls += 1
        raise AssertionError("preview must not run after HTTP 412")

    def fetch(self, video: str, include_comments: bool = False):
        self.fetch_calls += 1
        raise AssertionError("deep inspection must not run after HTTP 412")


class AdaptiveCandidateSource:
    def __init__(self):
        self.settings = SimpleNamespace(
            cookies_file=None,
            cookies_from_browser=None,
            rate_limit_seconds=0,
        )
        self.search_calls = 0
        self.preview_calls = 0

    def search(self, query: str, limit: int):
        self.search_calls += 1
        if self.search_calls > 1:
            raise AssertionError("candidate target should stop query expansion")
        return [
            SearchResult(
                source_id=f"BV123456789{index}",
                webpage_url=f"https://www.bilibili.com/video/BV123456789{index}",
                query=query,
                rank=index + 1,
                title=f"2025 TI杯电赛K题小车方案 {index}",
            )
            for index in range(limit)
        ]

    def preview(self, video: str):
        self.preview_calls += 1
        return VideoMetadata(
            bvid="BV1234567890",
            title="2025 TI杯电赛K题小车完整方案",
            description="智能车底盘和循迹控制",
            webpage_url=video,
        )

    def fetch(self, video: str, include_comments: bool = False):
        raw = sample_raw()
        raw.metadata.title = "2025 TI杯电赛K题小车完整方案"
        raw.metadata.description = "智能车底盘和循迹控制"
        raw.metadata.webpage_url = video
        return raw


class ResourcePrioritySource:
    def __init__(self):
        self.settings = SimpleNamespace(
            cookies_file=None,
            cookies_from_browser=None,
            rate_limit_seconds=0,
        )
        self.fetched: list[str] = []

    def search(self, query: str, limit: int):
        return [
            SearchResult(
                source_id=f"BV123456789{index}",
                webpage_url=f"https://www.bilibili.com/video/BV123456789{index}",
                query=query,
                rank=index + 1,
            )
            for index in range(5)
        ]

    def preview(self, video: str):
        has_resource = video.endswith("4")
        return VideoMetadata(
            bvid=video.rsplit("/", 1)[-1],
            title="STM32 PCB project tutorial",
            description=(
                "project github.com/example/stm32-board"
                if has_resource
                else "general tutorial"
            ),
            webpage_url=video,
        )

    def fetch(self, video: str, include_comments: bool = False):
        self.fetched.append(video)
        raw = sample_raw()
        raw.metadata.bvid = video.rsplit("/", 1)[-1]
        raw.metadata.title = "STM32 PCB project tutorial"
        raw.metadata.description = (
            "project github.com/example/stm32-board"
            if video.endswith("4")
            else "general tutorial"
        )
        raw.metadata.webpage_url = video
        return raw


class ExplicitCandidateSource:
    def __init__(self):
        self.settings = SimpleNamespace(
            cookies_file=None,
            cookies_from_browser=None,
            rate_limit_seconds=0,
        )
        self.fetch_calls = 0
        self.preview_calls = 0

    def search(self, query: str, limit: int):
        raise AssertionError("enough explicit candidates should skip internal search")

    def preview(self, video: str):
        self.preview_calls += 1
        return VideoMetadata(
            bvid=video.rsplit("/", 1)[-1],
            title="alternative implementation",
            description="curated by the host AI but sparse metadata",
            webpage_url=video,
        )

    def fetch(self, video: str, include_comments: bool = False):
        self.fetch_calls += 1
        raw = sample_raw()
        raw.metadata.bvid = video.rsplit("/", 1)[-1]
        raw.metadata.webpage_url = video
        return raw


class FilterFallbackSource(ExplicitCandidateSource):
    def search(self, query: str, limit: int):
        return [
            SearchResult(
                source_id=f"BV123456789{index}",
                webpage_url=f"https://www.bilibili.com/video/BV123456789{index}",
                query=query,
                rank=index + 1,
            )
            for index in range(5)
        ]


class LargeMismatchSource(FilterFallbackSource):
    def search(self, query: str, limit: int):
        return [
            SearchResult(
                source_id=f"av{100000 + index}",
                webpage_url=f"https://www.bilibili.com/video/av{100000 + index}",
                query=query,
                rank=index + 1,
            )
            for index in range(35)
        ]

    def preview(self, video: str):
        self.preview_calls += 1
        return VideoMetadata(
            bvid="BV1234567890",
            title="unrelated cooking vlog",
            description="daily life and food",
            webpage_url=video,
        )


def test_discovery_fails_fast_for_deterministic_authentication_error():
    source = FailingSearchSource([
        DataSourceError(
            "cookie database locked",
            category="authentication",
            deterministic=True,
        )
    ])

    report = DiscoveryPipeline(source).run(
        "find STM32 code", include_comments=False, bilibili_search="on"
    )

    assert source.calls == 1
    assert report.run_status == "failed"
    assert report.successful_queries == 0
    assert report.failed_queries == 1
    assert report.skipped_queries == len(report.expanded_queries) - 1
    assert report.stopped_at_query == report.expanded_queries[0]
    assert report.failure_category == "authentication"


def test_discovery_auth_preflight_stops_before_keyword_requests():
    source = FailingAuthPreflightSource()

    report = DiscoveryPipeline(source).run(
        "find STM32 code", include_comments=False, bilibili_search="on"
    )

    assert source.search_calls == 0
    assert report.run_status == "failed"
    assert report.failed_queries == 0
    assert report.skipped_queries == len(report.expanded_queries)
    assert report.stop_reason == "authentication_preflight"
    assert report.failure_category == "authentication"


def test_discovery_circuit_breaks_on_412_after_partial_success():
    source = FailingSearchSource([
        None,
        DataSourceError(
            "HTTP 412",
            category="rate_limited",
            deterministic=True,
        ),
    ])

    report = DiscoveryPipeline(source).run(
        "find STM32 code", include_comments=False, bilibili_search="on"
    )

    assert source.calls == 2
    assert report.run_status == "partial_success"
    assert report.successful_queries == 1
    assert report.failed_queries == 1
    assert report.skipped_queries == len(report.expanded_queries) - 2
    assert report.stop_reason == "http_412"
    assert report.failure_category == "rate_limited"
    assert len(report.candidates) == 0
    assert report.events[-1].status == "skipped_due_to_circuit_breaker"


def test_412_global_circuit_preserves_candidates_without_preview_or_deep_requests():
    source = CircuitAfterCandidateSource()

    report = DiscoveryPipeline(source).run(
        "2025 电赛 K题 小车",
        max_candidates=10,
        deep_limit=5,
        include_comments=True,
        bilibili_search="on",
    )

    assert source.search_calls == 2
    assert source.preview_calls == 0
    assert source.fetch_calls == 0
    assert report.candidates_found == 1
    assert report.candidates[0].source_id == "BV1234567890"
    assert report.videos == []
    assert any(
        event.phase == "deep_inspection"
        and event.status == "skipped_due_to_circuit_breaker"
        for event in report.events
    )


def test_search_stops_when_first_precise_query_reaches_candidate_target():
    source = AdaptiveCandidateSource()

    report = DiscoveryPipeline(source).run(
        "2025 电赛 K题 小车",
        max_candidates=20,
        deep_limit=5,
        include_comments=False,
        bilibili_search="on",
    )

    assert source.search_calls == 1
    assert source.preview_calls == 0
    assert report.successful_queries == 1
    assert report.failed_queries == 0
    assert report.skipped_queries == len(report.expanded_queries) - 1
    assert report.stop_reason == "candidate_target_reached"


def test_public_web_candidates_can_replace_internal_search_for_breadth():
    source = AdaptiveCandidateSource()
    urls = [f"https://www.bilibili.com/video/BV12345678{index:02d}" for index in range(20)]

    report = DiscoveryPipeline(source).run(
        "2025 电赛 K题 小车",
        max_candidates=20,
        deep_limit=2,
        include_comments=False,
        seed_video_urls=urls,
        bilibili_search="auto",
    )

    assert source.search_calls == 0
    assert report.stop_reason == "web_candidate_target_reached"
    assert report.candidates_found == 20
    assert all(item.provenance == ["web_index"] for item in report.candidates)
    assert len(report.videos) == 2


def test_sparse_public_candidates_trigger_one_broad_internal_query():
    source = AdaptiveCandidateSource()

    report = DiscoveryPipeline(source).run(
        "FOC motor controller",
        max_candidates=20,
        deep_limit=1,
        include_comments=False,
        seed_video_urls=["https://www.bilibili.com/video/BV1234567890"],
        bilibili_search="auto",
    )

    assert source.search_calls == 1
    assert report.stop_reason == "candidate_target_reached"
    assert report.candidates_found == 20
    assert len(report.videos) == 1


def test_internal_search_can_be_disabled_even_when_web_candidates_are_sparse():
    source = ExplicitCandidateSource()

    report = DiscoveryPipeline(source).run(
        "FOC motor controller",
        max_candidates=80,
        deep_limit=5,
        include_comments=False,
        seed_video_urls=["https://www.bilibili.com/video/BV1234567890"],
        bilibili_search="off",
    )

    assert report.stop_reason == "bilibili_search_disabled"
    assert source.fetch_calls == 1
    assert len(report.videos) == 1


def test_explicit_candidate_urls_are_deep_inspected_even_with_sparse_preview_metadata():
    source = ExplicitCandidateSource()
    urls = [f"https://www.bilibili.com/video/BV123456789{index}" for index in range(5)]
    checkpoint_sizes = []

    report = DiscoveryPipeline(source).run(
        "FOC STM32 AS5600 无刷电机开源控制器",
        max_candidates=20,
        deep_limit=2,
        include_comments=True,
        seed_video_urls=urls,
        bilibili_search="off",
        checkpoint=lambda videos: checkpoint_sizes.append(len(videos)),
    )

    assert source.fetch_calls == 2
    assert source.preview_calls == 0
    assert len(report.videos) == 2
    assert checkpoint_sizes == [1, 2]
    assert sum(
        event.status == "retained_explicit_candidate"
        for event in report.events
    ) >= 2


def test_learning_pipeline_skips_external_repository_verification(monkeypatch):
    source = ExplicitCandidateSource()

    def fail_if_called(_resources):
        raise AssertionError("learning mode must not verify repositories")

    monkeypatch.setattr(discovery_module, "inspect_external_resources", fail_if_called)
    report = DiscoveryPipeline(source).run(
        "我想学习STM32，请推荐教程视频",
        max_candidates=20,
        deep_limit=1,
        include_comments=False,
        seed_video_urls=["https://www.bilibili.com/video/BV1234567890"],
        seed_resource_urls=["https://github.com/example/course-assets"],
        discovery_mode="learning",
        bilibili_search="off",
    )

    assert report.discovery_mode == "learning"
    assert len(report.videos) == 1
    assert report.resources[0].inspection_status == "not_inspected"


def test_small_internal_candidate_pool_is_ranked_without_strict_filter_fallback():
    source = FilterFallbackSource()

    report = DiscoveryPipeline(source).run(
        "FOC STM32 AS5600 无刷电机开源控制器",
        max_candidates=20,
        deep_limit=2,
        include_comments=False,
        planned_queries=["FOC STM32 AS5600 无刷电机"],
        bilibili_search="on",
    )

    assert source.fetch_calls == 2
    assert len(report.videos) == 2
    assert not any(
        event.status == "retained_filter_fallback" for event in report.events
    )


def test_large_mismatched_internal_pool_is_not_restored_after_strict_filtering():
    source = LargeMismatchSource()

    report = DiscoveryPipeline(source).run(
        "FOC STM32 AS5600 motor controller",
        max_candidates=80,
        deep_limit=2,
        include_comments=False,
        planned_queries=["FOC STM32 AS5600 motor controller"],
        bilibili_search="on",
    )

    assert source.fetch_calls == 0
    assert report.videos == []
    assert sum(event.status == "rejected" for event in report.events) == 8
    assert not any(
        event.status == "retained_filter_fallback" for event in report.events
    )


def test_pipeline_spaces_requests_across_phases(monkeypatch):
    source = FailingSearchSource([None])
    source.settings.rate_limit_seconds = 2.0
    pipeline = DiscoveryPipeline(source)
    sleeps: list[float] = []
    monkeypatch.setattr(discovery_module.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(discovery_module.time, "sleep", sleeps.append)

    pipeline._pace_bilibili_request()
    pipeline._pace_bilibili_request()
    pipeline._pace_bilibili_request()

    assert sleeps == [2.5, 3.0]


def test_resource_bearing_video_is_prioritized_and_resources_become_primary(monkeypatch):
    source = ResourcePrioritySource()
    monkeypatch.setattr(discovery_module, "inspect_external_resources", lambda resources: None)

    report = DiscoveryPipeline(source).run(
        "STM32 PCB project",
        max_candidates=20,
        deep_limit=1,
        include_comments=False,
        planned_queries=["STM32 PCB project"],
        bilibili_search="on",
    )

    assert source.fetched[0].endswith("4")
    assert report.resources[0].locator == "https://github.com/example/stm32-board"
    assert report.resources[0].supporting_videos == [source.fetched[0]]
    assert report.videos[0].resources[0].kind == "code_repository"


def test_successful_empty_search_is_not_reported_as_system_failure():
    source = FailingSearchSource([None])

    report = DiscoveryPipeline(source).run(
        "find STM32 code", include_comments=False, bilibili_search="on"
    )

    assert report.run_status == "success"
    assert report.candidates_found == 0
    assert report.successful_queries == len(report.expanded_queries)
    assert report.failed_queries == 0
    assert report.skipped_queries == 0


def test_ai_planned_queries_override_deterministic_expansion():
    source = FailingSearchSource([None])
    planned = ["精确主题 官方题名", "精确主题 开源代码", "精确主题 开源代码"]

    report = DiscoveryPipeline(source).run(
        "一段自然语言需求",
        include_comments=False,
        planned_queries=planned,
        bilibili_search="on",
    )

    assert report.expanded_queries == ["精确主题 官方题名", "精确主题 开源代码"]
    assert source.calls == 2


def test_failed_discovery_does_not_replace_latest_success(tmp_path: Path):
    storage = FileStorage(tmp_path)
    success = DiscoveryReport(
        run_id="successful-run",
        run_status="success",
        requirement="same requirement",
        expanded_queries=["query"],
        candidates_found=0,
        deep_inspection_limit=1,
        successful_queries=1,
    )
    failed = DiscoveryReport(
        run_id="failed-run",
        run_status="failed",
        requirement="same requirement",
        expanded_queries=["query"],
        candidates_found=0,
        deep_inspection_limit=1,
        failed_queries=1,
        failure_category="authentication",
    )

    success_json, _ = storage.save_discovery(success)
    latest = success_json.parent / "latest.json"
    latest_before = latest.read_text(encoding="utf-8")
    failed_json, _ = storage.save_discovery(failed)

    assert success_json != failed_json
    assert success_json.exists() and failed_json.exists()
    assert latest.read_text(encoding="utf-8") == latest_before
    assert not list(tmp_path.rglob("*.tmp"))


def test_deep_inspection_checkpoint_is_atomic_and_machine_readable(tmp_path: Path):
    storage = FileStorage(tmp_path)
    video = DiscoveredVideo(
        bvid="BV1234567890",
        title="STM32 PCB",
        webpage_url="https://www.bilibili.com/video/BV1234567890",
        discovery_score=8,
        suitability_score=9,
        suitability_reason="complete design files",
        open_source_status="public_source_no_license",
        open_source_reason="repository is public",
    )

    path = storage.save_discovery_checkpoint("STM32 PCB", "resources", [video])
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["status"] == "in_progress"
    assert payload["completed_video_count"] == 1
    assert payload["videos"][0]["bvid"] == "BV1234567890"
    assert not list(tmp_path.rglob("*.tmp"))


def test_previous_discovery_links_are_reused_as_cache_seeds(tmp_path: Path):
    storage = FileStorage(tmp_path)
    report = DiscoveryReport(
        run_status="success",
        requirement="cached natural-language need",
        expanded_queries=["cached query"],
        candidates_found=1,
        deep_inspection_limit=1,
        successful_queries=1,
        candidates=[SearchCandidate(
            source_id="BV1234567890",
            webpage_url="https://www.bilibili.com/video/BV1234567890",
            matched_queries=["cached query"],
            best_rank=1,
            discovery_score=1,
        )],
        resources=[ExternalResource(
            locator="https://github.com/example/project",
            kind="code_repository",
            origin="public_web_direct",
            access_status="public_page",
            license_status="unverified",
        )],
    )
    storage.save_discovery(report)

    videos, resources = storage.load_discovery_seeds(report.requirement)

    assert videos == ["https://www.bilibili.com/video/BV1234567890"]
    assert resources == ["https://github.com/example/project"]


def test_http_412_persists_client_cooldown_state(tmp_path: Path):
    storage = FileStorage(tmp_path)
    report = DiscoveryReport(
        run_status="failed",
        requirement="test",
        expanded_queries=["test"],
        candidates_found=0,
        deep_inspection_limit=1,
        failed_queries=1,
        stop_reason="http_412",
        failure_category="rate_limited",
    )

    storage.save_discovery(report)
    state = storage.active_cooldown(now=report.completed_at)

    assert state is not None
    assert state["cooldown_state"] == "recommended"
    assert state["cooldown_reason"] == "risk_control"
    assert state["official_duration_known"] is False
    assert state["cooldown_policy"] == "adaptive_2_5_10"
    assert state["cooldown_minutes"] == 2
    assert state["consecutive_412_count"] == 1


def test_repeated_non_412_searches_never_create_client_cooldown(tmp_path: Path):
    storage = FileStorage(tmp_path)
    for requirement in ("first natural-language search", "second natural-language search"):
        storage.save_discovery(DiscoveryReport(
            run_status="success",
            requirement=requirement,
            expanded_queries=[requirement],
            candidates_found=0,
            deep_inspection_limit=1,
            stop_reason="candidate_target_reached",
        ))

    assert storage.active_cooldown() is None
    assert not (tmp_path / "data" / "state" / "bilibili_cooldown.json").exists()


def test_http_412_cooldown_escalates_and_resets_after_two_hours(tmp_path: Path):
    storage = FileStorage(tmp_path)
    first_at = datetime(2026, 8, 11, 2, 0, tzinfo=UTC)

    def save_412(at: datetime) -> dict:
        report = DiscoveryReport(
            run_status="failed",
            requirement="adaptive cooldown",
            expanded_queries=["test"],
            candidates_found=0,
            deep_inspection_limit=1,
            failed_queries=1,
            stop_reason="http_412",
            failure_category="rate_limited",
            completed_at=at,
        )
        storage.save_discovery(report)
        return storage.active_cooldown(now=at)

    first = save_412(first_at)
    second = save_412(first_at + timedelta(minutes=3))
    third = save_412(first_at + timedelta(minutes=9))
    reset = save_412(first_at + timedelta(hours=3))

    assert (first["cooldown_minutes"], first["consecutive_412_count"]) == (2, 1)
    assert (second["cooldown_minutes"], second["consecutive_412_count"]) == (5, 2)
    assert (third["cooldown_minutes"], third["consecutive_412_count"]) == (10, 3)
    assert (reset["cooldown_minutes"], reset["consecutive_412_count"]) == (2, 1)


def test_legacy_fixed_cooldown_is_read_as_first_adaptive_strike(tmp_path: Path):
    storage = FileStorage(tmp_path)
    occurred_at = datetime(2026, 8, 11, 2, 0, tzinfo=UTC)
    state_path = tmp_path / "data" / "state" / "bilibili_cooldown.json"
    storage._write_json(state_path, {
        "last_http_412_at": occurred_at.isoformat(),
        "cooldown_state": "recommended",
        "recommended_not_before": (occurred_at + timedelta(minutes=30)).isoformat(),
        "cooldown_reason": "risk_control",
        "official_duration_known": False,
    })

    state = storage.active_cooldown(now=occurred_at + timedelta(minutes=1))

    assert state["cooldown_minutes"] == 2
    assert state["consecutive_412_count"] == 1
    assert datetime.fromisoformat(state["recommended_not_before"]) == (
        occurred_at + timedelta(minutes=2)
    )


def test_expired_cooldown_ignores_inconsistent_stored_deadline_and_cleans_state(tmp_path: Path):
    storage = FileStorage(tmp_path)
    occurred_at = datetime(2026, 8, 11, 2, 0, tzinfo=UTC)
    state_path = tmp_path / "data" / "state" / "bilibili_cooldown.json"
    storage._write_json(state_path, {
        "last_http_412_at": occurred_at.isoformat(),
        "recommended_not_before": (occurred_at + timedelta(hours=10)).isoformat(),
        "cooldown_minutes": 2,
        "consecutive_412_count": 1,
    })

    state = storage.active_cooldown(now=occurred_at + timedelta(minutes=3))

    assert state is None
    assert not state_path.exists()


def test_future_clock_skew_does_not_create_an_unbounded_cooldown(tmp_path: Path):
    storage = FileStorage(tmp_path)
    now = datetime(2026, 8, 11, 2, 0, tzinfo=UTC)
    state_path = tmp_path / "data" / "state" / "bilibili_cooldown.json"
    storage._write_json(state_path, {
        "last_http_412_at": (now + timedelta(hours=2)).isoformat(),
        "recommended_not_before": (now + timedelta(hours=2, minutes=2)).isoformat(),
        "cooldown_minutes": 2,
        "consecutive_412_count": 1,
    })

    assert storage.active_cooldown(now=now) is None
    assert not state_path.exists()
