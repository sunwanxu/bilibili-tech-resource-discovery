from __future__ import annotations

import json
from urllib.error import HTTPError

import pytest

from bhka.web_discovery import (
    FirecrawlClient,
    FirecrawlError,
    build_firecrawl_queries,
    discover_with_firecrawl,
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
