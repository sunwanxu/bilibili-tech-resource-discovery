from __future__ import annotations

import json
from urllib.error import HTTPError

import pytest

from bhka.web_discovery import (
    FirecrawlClient,
    FirecrawlError,
    PublicIndexClient,
    build_firecrawl_queries,
    discover_with_firecrawl,
    discover_with_public_index,
    learning_search_focus,
)


def test_firecrawl_search_accepts_v2_web_shape() -> None:
    captured = {}

    def transport(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return {
            "success": True,
            "data": {
                "web": [
                    {
                        "url": "https://github.com/example/project",
                        "title": "Example project",
                        "description": "Reusable source code",
                        "markdown": "# Project",
                    }
                ]
            },
        }

    client = FirecrawlClient("fc-test-secret", transport=transport, timeout_seconds=7)
    hits = client.search("ESP32-C3 open source", limit=3)

    assert len(hits) == 1
    assert hits[0].url == "https://github.com/example/project"
    assert captured["timeout"] == 7
    assert captured["request"].full_url.endswith("/v2/search")
    assert captured["request"].get_header("Authorization") == "Bearer fc-test-secret"
    payload = json.loads(captured["request"].data)
    assert payload["limit"] == 3
    assert "scrapeOptions" not in payload


def test_discovery_collects_video_and_project_links_from_results() -> None:
    responses = [
        {
            "success": True,
            "data": {
                "web": [
                    {
                        "url": "https://www.bilibili.com/video/BV1xx411c7mD",
                        "description": "代码：https://github.com/example/firmware",
                    },
                    {"url": "https://oshwhub.com/example/board"},
                ]
            },
        }
    ] * 5

    def transport(_request, _timeout):
        return responses.pop(0)

    result = discover_with_firecrawl(
        FirecrawlClient("fc-test", transport=transport),
        "ESP32-C3 MQTT 智能家居",
        per_query=2,
    )

    assert result.result_count == 10
    assert result.video_urls == ["https://www.bilibili.com/video/BV1xx411c7mD"]
    assert result.resource_urls == [
        "https://github.com/example/firmware",
        "https://oshwhub.com/example/board",
    ]
    assert len(result.queries) == 5


def test_firecrawl_authentication_error_does_not_expose_key() -> None:
    def transport(request, _timeout):
        raise HTTPError(request.full_url, 401, "Unauthorized", {}, None)

    client = FirecrawlClient("fc-super-secret", transport=transport)
    with pytest.raises(FirecrawlError) as captured:
        client.search("test")

    assert captured.value.category == "authentication"
    assert "fc-super-secret" not in str(captured.value)


def test_firecrawl_queries_preserve_the_natural_language_requirement() -> None:
    requirement = "2025 电赛 K题 小车 开源代码"
    queries = build_firecrawl_queries(requirement)

    assert len(queries) == 5
    assert all("2025 电赛 K题 小车" in query for query in queries)
    assert any("bilibili.com/video" in query for query in queries)


def test_learning_queries_focus_on_courses_without_repository_searches() -> None:
    queries = build_firecrawl_queries(
        "我想学习一下AI短剧，我该看哪些视频",
        mode="learning",
    )

    assert len(queries) == 5
    assert all("site:bilibili.com/video" in query for query in queries)
    assert not any("GitHub" in query or "Gitee" in query for query in queries)
    assert any("从零 全流程" in query for query in queries)
    assert all("我想" not in query and "我该" not in query for query in queries)
    assert "AI短剧" in learning_search_focus("我想学习一下AI短剧，我该看哪些视频")


def test_discovery_keeps_results_when_one_firecrawl_query_fails() -> None:
    calls = 0

    def transport(_request, _timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise HTTPError("https://api.firecrawl.dev/v2/search", 429, "Limited", {}, None)
        return {
            "success": True,
            "data": {"web": [{"url": "https://github.com/example/project"}]},
        }

    result = discover_with_firecrawl(
        FirecrawlClient("fc-test", transport=transport),
        "ESP32-C3 MQTT 智能家居",
        per_query=2,
    )

    assert result.result_count == 4
    assert result.resource_urls == ["https://github.com/example/project"]
    assert result.failures == ["rate_limited"]


def test_discovery_canonicalizes_project_links_and_drops_navigation() -> None:
    response = {
        "success": True,
        "data": {
            "web": [
                {
                    "url": "https://github.com/example/project/tree/main/src",
                    "markdown": (
                        "https://github.com/example/project/commit/abc\n"
                        "https://github.com/login?return_to=/example/project\n"
                        "https://github.com/example\n"
                        "https://gitee.com/team/board/blob/master/README.md"
                    ),
                }
            ]
        },
    }

    result = discover_with_firecrawl(
        FirecrawlClient("fc-test", transport=lambda _request, _timeout: response),
        "ESP32-C3 MQTT 智能家居",
        per_query=2,
    )

    assert result.resource_urls == [
        "https://github.com/example/project",
        "https://gitee.com/team/board",
    ]


def test_discovery_accepts_numeric_bilibili_video_urls() -> None:
    response = {
        "success": True,
        "data": {"web": [{"url": "https://www.bilibili.com/video/116136268144356"}]},
    }

    result = discover_with_firecrawl(
        FirecrawlClient("fc-test", transport=lambda _request, _timeout: response),
        "motor controller",
        per_query=2,
    )

    assert result.video_urls == [
        "https://www.bilibili.com/video/116136268144356"
    ]


def test_malformed_ipv6_url_is_skipped_without_aborting_discovery() -> None:
    response = {
        "success": True,
        "data": {"web": [
            {"url": "https://[broken/resource"},
            {"url": "https://github.com/example/project"},
        ]},
    }

    result = discover_with_firecrawl(
        FirecrawlClient("fc-test", transport=lambda _request, _timeout: response),
        "motor controller",
        per_query=2,
    )

    assert result.resource_urls == ["https://github.com/example/project"]


def test_keyless_public_index_collects_bilibili_and_chinese_project_links() -> None:
    rss = """<?xml version="1.0" encoding="utf-8"?>
    <rss><channel>
      <item><title>PCB tutorial</title>
        <link>https://www.bilibili.com/video/BV1xx411c7mD</link>
        <description>Project https://oshwhub.com/example/blue-pill</description>
      </item>
      <item><title>Gitee mirror</title>
        <link>https://gitee.com/example/stm32-board</link>
        <description>source</description>
      </item>
    </channel></rss>"""
    captured = []

    def transport(request, timeout):
        captured.append((request.full_url, timeout))
        if "api.github.com" in request.full_url:
            return json.dumps({"items": [{
                "html_url": "https://github.com/example/blue-pill",
                "full_name": "example/blue-pill",
                "description": "PCB project",
            }]})
        return rss

    result = discover_with_public_index(
        PublicIndexClient(transport=transport, timeout_seconds=9),
        "STM32F103C8T6 PCB 开源资料",
        per_query=4,
    )

    assert len(captured) == 5
    assert all("?q=" in url for url, _ in captured)
    assert result.video_urls == ["https://www.bilibili.com/video/BV1xx411c7mD"]
    assert result.resource_urls == [
        "https://github.com/example/blue-pill",
        "https://oshwhub.com/example/blue-pill",
        "https://gitee.com/example/stm32-board",
    ]


def test_public_index_skips_malformed_result_url() -> None:
    rss = """<rss><channel>
      <item><title>bad</title><link>https://[broken/path</link></item>
      <item><title>good</title><link>https://github.com/example/project</link></item>
    </channel></rss>"""
    client = PublicIndexClient(transport=lambda _request, _timeout: rss)

    hits = client.search("STM32 PCB")

    assert [hit.url for hit in hits] == ["https://github.com/example/project"]


def test_github_search_relaxes_cjk_terms_when_exact_query_is_empty() -> None:
    urls = []

    def transport(request, _timeout):
        urls.append(request.full_url)
        if len(urls) == 1:
            return '{"items": []}'
        return json.dumps({"items": [{
            "html_url": "https://github.com/example/stm32-board",
            "full_name": "example/stm32-board",
        }]})

    hits = PublicIndexClient(transport=transport).search(
        "site:github.com STM32F103C8T6 PCB 最小系统 开源资料",
        limit=3,
    )

    assert len(urls) == 2
    assert "%E6%9C%80%E5%B0%8F" in urls[0]
    assert "%E6%9C%80%E5%B0%8F" not in urls[1]
    assert hits[0].url == "https://github.com/example/stm32-board"
