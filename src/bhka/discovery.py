from __future__ import annotations

import base64
import json
import math
import re
import time
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from .models import (
    DiscoveredVideo,
    DiscoveryEvent,
    DiscoveryReport,
    ExternalResource,
    RawVideoData,
    SearchCandidate,
    SearchResult,
)
from .source import DataSourceError, YtDlpDataSource, normalize_video_id

URL_RE = re.compile(r"https?://[^\s<>\"'\\，。；、）)】]+", re.IGNORECASE)
BARE_RESOURCE_RE = re.compile(
    r"(?<![\w@])((?:www\.)?(?:github\.com|gitee\.com|gitcode\.net|codeberg\.org|"
    r"oshwhub\.com)/[^\s<>\"'\\,;，。；：！？（）【】《》]+)",
    re.IGNORECASE,
)
QQ_GROUP_RE = re.compile(
    r"(?:QQ|qq群|QQ交流群|交流群|资料群)\s*[：:：号]?\s*(\d{6,12})",
    re.IGNORECASE,
)
LICENSE_RE = re.compile(
    r"\b(?:MIT|Apache[- ]?2\.0|GPL[- ]?[23](?:\.0)?|LGPL[- ]?[23](?:\.0)?|"
    r"BSD[- ]?[23]-Clause|MPL[- ]?2\.0|CERN[- ]?OHL)\b|开源协议\s*[：:]?\s*\S+",
    re.IGNORECASE,
)
PROMISE_RE = re.compile(r"(?:之后|后续|等.*后|稍后|未来|到时|完成后|测试后).{0,8}开源|会开源")
FULL_PROCESS_TERMS = ("全流程", "手把手", "保姆级", "实战", "从零", "零基础", "制作", "复刻")
KNOWN_TECH_TERMS = (
    "STM32", "MSPM0", "ESP32", "PCB", "嘉立创EDA", "立创EDA", "最小系统", "原理图",
    "布局", "布线", "打板", "焊接", "开源", "代码", "源码", "电赛", "教程", "设计方案",
)
FOCUS_TERMS = (
    "嘉立创EDA", "立创EDA", "最小系统", "STM32", "MSPM0", "ESP32", "PCB", "电赛",
    "原理图", "布局", "布线", "打板", "焊接",
)
RESOURCE_INTENT_TERMS = {
    "开源", "开源代码", "源码", "设计方案", "方案", "项目资料", "资料", "不同技术路线",
    "不同方案", "教程", "实战", "复刻", "赛后复盘", "github", "gitee", "立创开源",
}
CONVERSATIONAL_TERMS = {
    "我", "想", "想要", "需要", "帮我", "寻找", "查找", "搜索", "适合", "如何", "怎么",
}


def _normalized_terms(value: str) -> list[str]:
    return [
        item
        for item in re.split(r"[\s,，。；;、/]+", value.strip())
        if item
    ]


def extract_query_anchors(requirement: str) -> list[str]:
    """Preserve user entities without relying on a task-specific vocabulary."""
    anchors: list[str] = []

    def add(term: str) -> None:
        lowered = term.lower()
        if term and not any(lowered in item.lower() for item in anchors):
            anchors.append(term)

    for term in _normalized_terms(requirement):
        lowered = term.lower()
        if lowered in RESOURCE_INTENT_TERMS or term in CONVERSATIONAL_TERMS:
            continue
        if any(term.startswith(prefix) for prefix in CONVERSATIONAL_TERMS):
            continue
        if len(term) <= 24:
            add(term)
    for year in re.findall(r"\b20\d{2}\b", requirement):
        add(year)
    for problem in re.findall(r"(?<![A-Za-z])([A-Za-z])\s*题", requirement):
        add(f"{problem.upper()}题")
    for quoted in re.findall(r"[\"“‘]([^\"”’]{2,40})[\"”’]", requirement):
        add(quoted)
    for term in sorted(FOCUS_TERMS, key=len, reverse=True):
        if term.lower() in requirement.lower():
            add(term)
    return anchors


def extract_hard_anchors(requirement: str) -> list[str]:
    anchors: list[str] = []
    anchors.extend(re.findall(r"\b20\d{2}\b", requirement))
    anchors.extend(
        f"{problem.upper()}题"
        for problem in re.findall(r"(?<![A-Za-z])([A-Za-z])\s*题", requirement)
    )
    anchors.extend(re.findall(r"[\"“‘]([^\"”’]{2,40})[\"”’]", requirement))
    anchors.extend(re.findall(
        r"(?<![A-Za-z0-9-])(?=[A-Za-z0-9-]*[A-Za-z])(?=[A-Za-z0-9-]*\d)"
        r"[A-Za-z][A-Za-z0-9-]{2,}",
        requirement,
    ))
    anchors.extend(re.findall(r"\b[A-Z]{2,8}\b", requirement))
    return list(dict.fromkeys(anchors))


def expand_queries(requirement: str, limit: int = 8) -> list[str]:
    """Expand a natural-language need into a bounded, explainable query set."""
    base = " ".join(requirement.split()).strip()
    if not base:
        raise ValueError("Requirement cannot be empty")
    if not 3 <= limit <= 12:
        raise ValueError("Query expansion limit must be between 3 and 12")

    focus = " ".join(extract_query_anchors(base)) or base[:48]
    intents = [
        "教程 实战",
        "开源代码",
        "源码 GitHub",
        "源码 Gitee",
        "项目资料",
        "设计方案",
        "不同技术路线",
    ]

    queries = [focus, *(f"{focus} {intent}" for intent in intents)]
    result = []
    for query in queries:
        normalized = " ".join(query.split())
        if normalized and normalized not in result:
            result.append(normalized)
    return result[:limit]


def aggregate_candidates(results: list[SearchResult]) -> list[SearchCandidate]:
    grouped: dict[str, list[SearchResult]] = defaultdict(list)
    for result in results:
        grouped[result.source_id].append(result)
    candidates = []
    for source_id, hits in grouped.items():
        matched_queries = list(dict.fromkeys(hit.query for hit in hits))
        best_rank = min(hit.rank for hit in hits)
        score = len(matched_queries) * 4 + sum(5 / hit.rank for hit in hits)
        candidates.append(SearchCandidate(
            source_id=source_id,
            webpage_url=hits[0].webpage_url,
            matched_queries=matched_queries,
            best_rank=best_rank,
            discovery_score=round(score, 4),
            provenance=list(dict.fromkeys(hit.provenance for hit in hits)),
        ))
    return sorted(candidates, key=lambda item: (-item.discovery_score, item.best_rank))


def seed_video_results(urls: list[str], requirement: str) -> list[SearchResult]:
    """Normalize public-web Bilibili candidates supplied by the host AI."""
    results: list[SearchResult] = []
    seen: set[str] = set()
    for url in urls:
        try:
            bvid = normalize_video_id(url)
        except ValueError:
            continue
        if bvid in seen:
            continue
        seen.add(bvid)
        results.append(SearchResult(
            source_id=bvid,
            webpage_url=f"https://www.bilibili.com/video/{bvid}",
            query=requirement,
            rank=len(results) + 1,
            provenance="web_index",
        ))
    return results


def prepare_direct_resources(urls: list[str]) -> list[ExternalResource]:
    """Normalize and inspect public project links found independently of Bilibili."""
    resources: list[ExternalResource] = []
    seen: set[str] = set()
    for value in urls:
        locator = value.strip().rstrip(".,;:!?")
        if not locator or locator in seen:
            continue
        parsed = urlparse(locator)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        seen.add(locator)
        kind, access = classify_resource(locator)
        resources.append(ExternalResource(
            locator=locator,
            kind=kind,
            origin="public_web_direct",
            access_status=access,
            license_status="unverified",
            origins=["public_web_direct"],
        ))
    inspect_external_resources(resources)
    return resources


def _resource_locators(text: str) -> list[str]:
    values = list(URL_RE.findall(text))
    values.extend(f"https://{match}" for match in BARE_RESOURCE_RE.findall(text))
    result: list[str] = []
    for value in values:
        locator = value.rstrip(".,;:!?)]}，。；：！？）】》")
        if locator and locator not in result:
            result.append(locator)
    return result


def extract_resources(raw: RawVideoData) -> list[ExternalResource]:
    evidence = [("description", raw.metadata.description)]
    evidence.extend(("comment", comment.text) for comment in raw.comments)
    evidence.extend(("subtitle", track.text) for track in raw.subtitles)
    resources: list[ExternalResource] = []
    seen: set[str] = set()
    for origin, text in evidence:
        for locator in _resource_locators(text):
            if locator in seen:
                continue
            seen.add(locator)
            kind, access = classify_resource(locator)
            resources.append(ExternalResource(
                locator=locator,
                kind=kind,
                origin=origin,
                access_status=access,
                license_status="unverified",
                origins=[origin],
                supporting_videos=[raw.metadata.webpage_url],
            ))
        for group in QQ_GROUP_RE.findall(text):
            locator = f"QQ group {group}"
            if locator not in seen:
                seen.add(locator)
                resources.append(ExternalResource(
                    locator=locator,
                    kind="community_group",
                    origin=origin,
                    access_status="login_or_join_required",
                    license_status="unknown",
                    origins=[origin],
                    supporting_videos=[raw.metadata.webpage_url],
                ))
    return resources


def classify_resource(locator: str) -> tuple[str, str]:
    host = urlparse(locator).netloc.lower()
    if host in {
        "github.com",
        "www.github.com",
        "gitee.com",
        "www.gitee.com",
        "gitcode.net",
        "www.gitcode.net",
        "codeberg.org",
        "www.codeberg.org",
    }:
        return "code_repository", "public_page"
    if "oshwhub.com" in host:
        return "hardware_project", "public_page_clone_may_require_login"
    if "pan.baidu.com" in host or "pan.quark.cn" in host:
        return "cloud_drive", "login_or_app_may_be_required"
    if "bilibili.com" in host or "b23.tv" in host:
        return "bilibili_reference", "public_page"
    if "weixin.qq.com" in host or "mp.weixin.qq.com" in host:
        return "wechat_resource", "wechat_may_be_required"
    if urlparse(locator).path.lower().endswith(".pdf"):
        return "document", "public_page"
    return "external_link", "unverified"


def infer_repository_artifacts(paths: list[str], readme: str = "") -> dict[str, str]:
    lowered_paths = [path.lower() for path in paths]

    def found(*patterns: str) -> bool:
        return any(
            any(pattern in path for pattern in patterns)
            for path in lowered_paths
        )

    source_extensions = (".c", ".cpp", ".cc", ".h", ".hpp", ".ino", ".py", ".rs")
    artifacts = {
        "schematic": "present" if found(
            ".kicad_sch", ".schdoc", ".epro", ".epro2", "schematic", "原理图"
        ) else "not_evidenced",
        "pcb": "present" if found(
            ".kicad_pcb", ".pcbdoc", ".epro", ".epro2", "pcb", "嘉立创工程"
        ) else "not_evidenced",
        "bom": "present" if found("bom", "bill-of-material", "物料清单") else "not_evidenced",
        "gerber": "present" if found("gerber", ".gbr", ".gtl", ".gbl") else "not_evidenced",
        "source_code": "present" if any(
            path.endswith(source_extensions) for path in lowered_paths
        ) else "not_evidenced",
        "documentation": "present" if found("readme", "docs/", ".pdf", "说明", "手册") else "not_evidenced",
        "hardware_validation": "present" if re.search(
            r"实物|已验证|焊接|上板|prototype|tested on (?:real )?hardware|hardware tested",
            readme,
            re.IGNORECASE,
        ) else "not_evidenced",
    }
    return artifacts


def _read_public_json(url: str, timeout: int) -> dict:
    request = Request(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "bhka/0.2"},
    )
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _inspect_github(resource: ExternalResource, parts: list[str], timeout: int) -> list[str]:
    owner, repository = parts[:2]
    repository = repository.removesuffix(".git")
    base_url = f"https://api.github.com/repos/{owner}/{repository}"
    repository_data = _read_public_json(base_url, timeout)
    branch = repository_data.get("default_branch") or "main"
    tree = _read_public_json(
        f"{base_url}/git/trees/{quote(branch, safe='')}?recursive=1",
        timeout,
    )
    paths = [item.get("path", "") for item in tree.get("tree") or [] if item.get("type") == "blob"]
    readme = ""
    try:
        readme_data = _read_public_json(f"{base_url}/readme", timeout)
        encoded = readme_data.get("content") or ""
        readme = base64.b64decode(encoded).decode("utf-8", errors="ignore") if encoded else ""
    except (OSError, ValueError, json.JSONDecodeError):
        resource.verification_notes.append("GitHub README could not be read.")
    license_data = repository_data.get("license") or {}
    spdx = str(license_data.get("spdx_id") or "").strip()
    resource.license_status = (
        f"verified_github_spdx:{spdx}"
        if spdx and spdx != "NOASSERTION"
        else "github_license_not_identified"
    )
    resource.artifacts = infer_repository_artifacts(paths, readme)
    resource.artifacts["license"] = (
        "present" if resource.license_status.startswith("verified_github_spdx:")
        else "not_evidenced"
    )
    resource.inspection_status = "inspected"
    if tree.get("truncated"):
        resource.verification_notes.append("GitHub file tree was truncated; completeness may be understated.")
    resource.verification_notes.append(f"Inspected {len(paths)} repository files on branch {branch}.")
    return URL_RE.findall(readme)


def _inspect_oshwhub(resource: ExternalResource, timeout: int) -> list[str]:
    request = Request(resource.locator, headers={"User-Agent": "Mozilla/5.0 bhka/0.2"})
    with urlopen(request, timeout=timeout) as response:
        html = response.read(1_000_000).decode("utf-8", errors="ignore")
    match = re.search(
        r"开源协议.{0,500}?(GPL\s*[23]\.0|LGPL\s*[23]\.0|MIT|Apache[- ]?2\.0|"
        r"CC\s+BY(?:-NC)?\s*[34]\.0|Public Domain)",
        html,
        re.IGNORECASE | re.DOTALL,
    )
    resource.license_status = (
        f"platform_claimed_license:{match.group(1)}"
        if match
        else "platform_license_not_identified"
    )
    clone_available = "克隆工程" in html or "打开设计图" in html
    resource.artifacts = {
        "schematic": "platform_project_available" if clone_available else "unknown",
        "pcb": "platform_project_available" if clone_available else "unknown",
        "bom": "not_evidenced" if "暂无BOM" in html else "unknown",
        "gerber": "present" if re.search(r"Gerber|\.gbr", html, re.IGNORECASE) else "not_evidenced",
        "source_code": "present" if re.search(r"源码|源代码|测试代码", html) else "not_evidenced",
        "documentation": "present" if re.search(r"说明|文档|手册|教程", html) else "not_evidenced",
        "hardware_validation": "present" if re.search(r"实物图|已验证|焊接测试", html) else "not_evidenced",
        "license": "platform_claimed" if match else "not_evidenced",
    }
    resource.inspection_status = "inspected"
    resource.verification_notes.append(
        "Platform HTML was inspected; cloning, attachments, and platform terms may require login."
    )
    return URL_RE.findall(html)


def _inspect_gitee(resource: ExternalResource, timeout: int) -> list[str]:
    request = Request(resource.locator, headers={"User-Agent": "Mozilla/5.0 bhka/0.3"})
    with urlopen(request, timeout=timeout) as response:
        html = response.read(1_000_000).decode("utf-8", errors="ignore")
    license_match = LICENSE_RE.search(html)
    resource.license_status = (
        f"platform_claimed_license:{license_match.group(0)}"
        if license_match
        else "gitee_license_not_identified"
    )
    paths = re.findall(
        r"[A-Za-z0-9_./-]+\.(?:c|cc|cpp|h|hpp|ino|py|rs|kicad_sch|kicad_pcb|"
        r"SchDoc|PcbDoc|epro|epro2|pdf|gbr|zip|md)",
        html,
        re.IGNORECASE,
    )
    resource.artifacts = infer_repository_artifacts(paths, html)
    resource.artifacts["license"] = "present" if license_match else "not_evidenced"
    resource.inspection_status = "inspected"
    resource.verification_notes.append("Inspected the public Gitee project page.")
    return _resource_locators(html)


def _canonical_resource_key(locator: str) -> str:
    parsed = urlparse(locator.strip())
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.rstrip("/").lower()
    return f"{host}{path}"


def merge_resource_pool(*groups: list[ExternalResource]) -> list[ExternalResource]:
    """Merge the same resource across web, descriptions, comments, and subtitles."""
    merged: dict[str, ExternalResource] = {}
    license_strength = {
        "unverified": 0,
        "unknown": 0,
        "verification_failed": 0,
        "github_license_not_identified": 1,
        "gitee_license_not_identified": 1,
    }
    for resource in (item for group in groups for item in group):
        key = _canonical_resource_key(resource.locator)
        if not key:
            continue
        current = merged.get(key)
        if current is None:
            current = resource.model_copy(deep=True)
            current.origins = list(dict.fromkeys([resource.origin, *resource.origins]))
            current.supporting_videos = list(dict.fromkeys(resource.supporting_videos))
            merged[key] = current
            continue
        current.origins = list(dict.fromkeys([
            *current.origins,
            resource.origin,
            *resource.origins,
        ]))
        current.supporting_videos = list(dict.fromkeys([
            *current.supporting_videos,
            *resource.supporting_videos,
        ]))
        current.verification_notes = list(dict.fromkeys([
            *current.verification_notes,
            *resource.verification_notes,
        ]))
        current.artifacts.update({
            name: value
            for name, value in resource.artifacts.items()
            if value not in {"unknown", "not_evidenced"}
            or name not in current.artifacts
        })
        current_strength = (
            4 if current.license_status.startswith("verified_")
            else 3 if current.license_status.startswith("platform_claimed_license:")
            else license_strength.get(current.license_status, 2)
        )
        incoming_strength = (
            4 if resource.license_status.startswith("verified_")
            else 3 if resource.license_status.startswith("platform_claimed_license:")
            else license_strength.get(resource.license_status, 2)
        )
        if incoming_strength > current_strength:
            current.license_status = resource.license_status
        if resource.inspection_status == "inspected":
            current.inspection_status = "inspected"
    return list(merged.values())


def rank_resources(resources: list[ExternalResource]) -> list[ExternalResource]:
    """Make usable project resources the primary ranked output."""
    for resource in resources:
        reasons: list[str] = []
        if resource.license_status.startswith("verified_github_spdx:"):
            score = 8.5
            resource.usability_status = "usable_open_source_verified"
            reasons.append("verified repository license")
        elif resource.license_status.startswith("platform_claimed_license:"):
            score = 7.0
            resource.usability_status = "usable_platform_license_claim"
            reasons.append("public project with a platform license claim")
        elif resource.kind in {"code_repository", "hardware_project"}:
            score = 5.5 if resource.inspection_status == "inspected" else 4.5
            resource.usability_status = "usable_source_license_unverified"
            reasons.append("public source or hardware project; license not verified")
        elif resource.kind == "cloud_drive":
            score = 2.5
            resource.usability_status = "restricted_shared_files"
            reasons.append("shared files require manual access and have unclear reuse rights")
        else:
            score = 2.0
            resource.usability_status = "lead_requires_review"
            reasons.append("resource lead requires manual review")
        artifact_count = sum(
            value in {"present", "platform_project_available"}
            for value in resource.artifacts.values()
        )
        if artifact_count:
            score += min(1.0, artifact_count * 0.2)
            reasons.append(f"{artifact_count} evidenced project artifacts")
        if resource.supporting_videos:
            score += min(0.5, len(resource.supporting_videos) * 0.25)
            reasons.append("supported by Bilibili evidence")
        if resource.inspection_status == "verification_failed":
            score -= 2.0
            resource.usability_status = "unavailable_or_unverified"
            reasons.append("public verification failed")
        resource.resource_score = round(max(0.0, min(10.0, score)), 1)
        resource.resource_value_reason = "; ".join(reasons)
    return sorted(
        resources,
        key=lambda item: (-item.resource_score, item.kind, item.locator.lower()),
    )


def inspect_external_resources(
    resources: list[ExternalResource],
    timeout: int = 8,
    limit: int = 30,
) -> None:
    """Inspect supported public hosts while preserving login and evidence boundaries."""
    seen = {resource.locator for resource in resources}
    index = 0
    while index < len(resources) and index < limit:
        resource = resources[index]
        index += 1
        if resource.inspection_status == "inspected":
            continue
        parsed = urlparse(resource.locator)
        host = parsed.netloc.lower()
        parts = [part for part in parsed.path.split("/") if part]
        nested_links: list[str] = []
        try:
            if host in {"github.com", "www.github.com"} and len(parts) >= 2:
                nested_links = _inspect_github(resource, parts, timeout)
            elif host in {"gitee.com", "www.gitee.com"} and len(parts) >= 2:
                nested_links = _inspect_gitee(resource, timeout)
            elif "oshwhub.com" in host:
                nested_links = _inspect_oshwhub(resource, timeout)
            elif resource.access_status in {
                "login_or_app_may_be_required",
                "login_or_join_required",
                "wechat_may_be_required",
            }:
                resource.inspection_status = "blocked_or_human_review_required"
                resource.verification_notes.append(
                    "Content was not inspected because login, an app, or group membership may be required."
                )
        except (OSError, ValueError, json.JSONDecodeError):
            resource.license_status = "verification_failed"
            resource.inspection_status = "verification_failed"
            resource.verification_notes.append("The public resource could not be inspected.")
        for locator in nested_links:
            locator = locator.split("\\", 1)[0].rstrip(".,;:!?")
            if locator in seen:
                continue
            kind, access = classify_resource(locator)
            allowed_nested_kinds = (
                {"code_repository", "cloud_drive"}
                if resource.kind == "hardware_project"
                else {"hardware_project", "cloud_drive", "document"}
            )
            if kind not in allowed_nested_kinds:
                continue
            seen.add(locator)
            resources.append(ExternalResource(
                locator=locator,
                kind=kind,
                origin=f"nested_from:{resource.kind}",
                access_status=access,
                license_status="unverified",
            ))
            if len(resources) >= limit:
                break


def verify_resource_licenses(resources: list[ExternalResource], timeout: int = 8) -> None:
    """Backward-compatible wrapper for callers using the earlier function name."""
    inspect_external_resources(resources, timeout)


def classify_open_source(raw: RawVideoData, resources: list[ExternalResource]) -> tuple[str, str]:
    text = "\n".join([
        raw.metadata.title,
        raw.metadata.description,
        *(comment.text for comment in raw.comments),
    ])
    repository_kinds = {"code_repository", "hardware_project"}
    repositories = [resource for resource in resources if resource.kind in repository_kinds]
    verified = [
        resource for resource in repositories
        if resource.license_status.startswith("verified_github_spdx:")
    ]
    if verified:
        licenses = ", ".join(
            resource.license_status.split(":", 1)[1] for resource in verified
        )
        incomplete = [
            resource
            for resource in resources
            if resource not in verified
            and resource.kind in {"code_repository", "hardware_project", "cloud_drive"}
            and not resource.license_status.startswith("verified_")
        ]
        if incomplete:
            return (
                "license_scope_incomplete",
                (
                    f"Verified license evidence ({licenses}) covers only part of the linked "
                    "resources; the complete project license remains unverified."
                ),
            )
        return "explicit_license_verified", f"Repository license verified through GitHub: {licenses}."
    platform_claims = [
        resource for resource in repositories
        if resource.license_status.startswith("platform_claimed_license:")
    ]
    if platform_claims:
        licenses = ", ".join(
            resource.license_status.split(":", 1)[1] for resource in platform_claims
        )
        return (
            "platform_license_claim_terms_need_review",
            f"The hardware platform labels the project {licenses}; platform-specific terms may add restrictions.",
        )
    if LICENSE_RE.search(text):
        for resource in repositories:
            resource.license_status = "license_mentioned_in_bilibili_evidence"
        return "explicit_license_mentioned", "Bilibili evidence names a recognized license; repository still needs direct verification."
    if repositories:
        return (
            "public_repository_license_unverified",
            "A public code or hardware-project link exists, but its license was not verified in this pass.",
        )
    if PROMISE_RE.search(text):
        return "promised_open_source_link_missing", "The uploader promises a future release, but no repository link was found."
    if "开源" in text:
        return "claimed_open_source_link_missing", "The video claims open source, but no verifiable repository link was found."
    if any(resource.kind == "cloud_drive" for resource in resources):
        return "shared_files_license_unknown", "Files are shared through a cloud drive without license evidence."
    return "no_open_source_evidence", "No repository, license, or concrete open-source evidence was found."


def suitability(raw: RawVideoData, requirement: str, resources: list[ExternalResource]) -> tuple[float, str]:
    text = f"{raw.metadata.title}\n{raw.metadata.description}".lower()
    terms = [term for term in KNOWN_TECH_TERMS if term.lower() in requirement.lower()]
    matches = [term for term in terms if term.lower() in text]
    score = 3.5 + min(2.5, len(matches) * 0.5)
    reasons = []
    if matches:
        reasons.append("matches " + ", ".join(matches[:5]))
    if any(term.lower() in text for term in FULL_PROCESS_TERMS):
        score += 1.0
        reasons.append("signals a guided or full-process format")
    if any(resource.kind in {"code_repository", "hardware_project"} for resource in resources):
        score += 1.5
        reasons.append("includes a public project or repository")
    elif resources:
        score += 0.5
        reasons.append("includes external learning resources")
    if raw.comments:
        score += 0.5
        reasons.append("top comments were available for cross-checking")
    artifact_count = sum(
        value in {"present", "platform_project_available"}
        for resource in resources
        for value in resource.artifacts.values()
    )
    if artifact_count:
        score += min(1.5, artifact_count * 0.25)
        reasons.append(f"verified {artifact_count} project-artifact signals")
    if PROMISE_RE.search(text) and not resources:
        score -= 1.0
        reasons.append("open-source material is promised but not linked")
    return round(max(0.0, min(10.0, score)), 1), "; ".join(reasons) or "limited matching evidence"


def preview_relevance(title: str, description: str, requirement: str) -> float:
    text = f"{title}\n{description}".lower()
    score = 0.0
    for term in extract_query_anchors(requirement):
        if term.lower() in text:
            score += 1.0
    if any(term.lower() in text for term in FULL_PROCESS_TERMS):
        score += 1.0
    if URL_RE.search(description) or "开源" in text:
        score += 1.0
    return score


def passes_hard_relevance(title: str, description: str, requirement: str) -> bool:
    """Reject obvious semantic mismatches before subtitle/comment inspection."""
    compact_text = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", f"{title}\n{description}".lower())
    mandatory = list(dict.fromkeys([
        *re.findall(r"\b20\d{2}\b", requirement),
        *(f"{letter.upper()}题" for letter in re.findall(
            r"(?<![A-Za-z])([A-Za-z])\s*题",
            requirement,
        )),
        *re.findall(r"[\"“‘]([^\"”’]{2,40})[\"”’]", requirement),
    ]))
    if any(
        re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", anchor.lower()) not in compact_text
        for anchor in mandatory
    ):
        return False
    mandatory_lowered = {item.lower() for item in mandatory}
    signals = list(dict.fromkeys([
        *(
            term
            for term in extract_hard_anchors(requirement)
            if term.lower() not in mandatory_lowered
        ),
        *(
            term
            for term in extract_query_anchors(requirement)
            if term.lower() not in mandatory_lowered
        ),
    ]))
    if not signals:
        return True
    return any(
        re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", term.lower()) in compact_text
        for term in signals
    )


class DiscoveryPipeline:
    def __init__(self, source: YtDlpDataSource):
        self.source = source
        self._last_bilibili_request_at: float | None = None
        self._request_sequence = 0

    def _pace_bilibili_request(self) -> None:
        """Space requests across search, preview, and inspection subprocesses."""
        base = max(0.0, float(getattr(self.source.settings, "rate_limit_seconds", 0.0)))
        if self._last_bilibili_request_at is not None and base:
            multiplier = 1.0 + min(self._request_sequence, 4) * 0.25
            required_gap = min(8.0, base * multiplier)
            elapsed = time.monotonic() - self._last_bilibili_request_at
            if elapsed < required_gap:
                time.sleep(required_gap - elapsed)
        self._last_bilibili_request_at = time.monotonic()
        self._request_sequence += 1

    def run(
        self,
        requirement: str,
        max_candidates: int = 50,
        deep_limit: int = 8,
        include_comments: bool = True,
        planned_queries: list[str] | None = None,
        seed_video_urls: list[str] | None = None,
        seed_resource_urls: list[str] | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> DiscoveryReport:
        started_at = datetime.now(UTC)
        self._last_bilibili_request_at = None
        self._request_sequence = 0
        if not 10 <= max_candidates <= 200:
            raise ValueError("max_candidates must be between 10 and 200")
        if not 1 <= deep_limit <= 12:
            raise ValueError("deep_limit must be between 1 and 12")
        if planned_queries:
            queries = list(dict.fromkeys(
                " ".join(query.split())
                for query in planned_queries
                if query.strip()
            ))
            if not 1 <= len(queries) <= 8:
                raise ValueError("planned_queries must contain between 1 and 8 unique queries")
        else:
            queries = expand_queries(requirement)
        per_query = min(20, max(5, math.ceil(max_candidates / len(queries)) + 2))
        hits = seed_video_results(seed_video_urls or [], requirement)
        direct_resources = prepare_direct_resources(seed_resource_urls or [])
        limitations: list[str] = []
        events: list[DiscoveryEvent] = []
        successful_queries = 0
        failed_queries = 0
        skipped_queries = 0
        stopped_at_query: str | None = None
        stop_reason: str | None = None
        failure_category: str | None = None
        target = min(max_candidates, max(5, deep_limit))
        skip_internal_search = len({hit.source_id for hit in hits}) >= target
        if skip_internal_search:
            skipped_queries = len(queries)
            stop_reason = "web_candidate_target_reached"
            events.append(DiscoveryEvent(
                phase="candidate_discovery",
                status="web_candidate_target_reached",
                detail=f"{len(hits)} public-web video candidates",
            ))
        if (
            not skip_internal_search
            and (self.source.settings.cookies_file or self.source.settings.cookies_from_browser)
        ):
            if progress:
                progress("Verifying configured Bilibili login...")
            try:
                self._pace_bilibili_request()
                auth = self.source.verify_auth()
            except DataSourceError as exc:
                events.append(DiscoveryEvent(
                    phase="authentication",
                    status="failed",
                    detail=exc.category,
                ))
                seeded_candidates = aggregate_candidates(hits)[:max_candidates]
                return DiscoveryReport(
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                    run_status=(
                        "partial_success" if seeded_candidates or direct_resources else "failed"
                    ),
                    requirement=requirement,
                    expanded_queries=queries,
                    candidates_found=len(seeded_candidates),
                    deep_inspection_limit=deep_limit,
                    successful_queries=0,
                    failed_queries=0,
                    skipped_queries=len(queries),
                    stop_reason="authentication_preflight",
                    failure_category=exc.category,
                    candidates=seeded_candidates,
                    resources=rank_resources(merge_resource_pool(direct_resources)),
                    direct_resources=direct_resources,
                    events=events,
                    evidence_limitations=[str(exc)],
                )
            events.append(DiscoveryEvent(
                phase="authentication",
                status=auth.status,
            ))
            if auth.status == "invalid":
                limitations.append(
                    "Configured Bilibili session is not logged in; coverage is limited to public data."
                )
        for index, query in enumerate(queries, 1):
            if skip_internal_search:
                break
            if progress:
                progress(f"Searching {index}/{len(queries)}: {query}")
            try:
                self._pace_bilibili_request()
                query_hits = self.source.search(query, per_query)
                hits.extend(query_hits)
                successful_queries += 1
                events.append(DiscoveryEvent(
                    phase="search",
                    status="success",
                    query=query,
                    detail=f"{len(query_hits)} results",
                ))
                unique_hits = len({hit.source_id for hit in hits})
                if unique_hits >= target and index < len(queries):
                    skipped_queries = len(queries) - index
                    stopped_at_query = query
                    stop_reason = "candidate_target_reached"
                    events.append(DiscoveryEvent(
                        phase="search",
                        status="stopped_early",
                        query=query,
                        detail=f"candidate target reached: {unique_hits}/{target}",
                    ))
                    break
            except DataSourceError as exc:
                limitations.append(str(exc))
                events.append(DiscoveryEvent(
                    phase="search",
                    status="http_412" if exc.category == "rate_limited" else "failed",
                    query=query,
                    detail=exc.category,
                ))
                if not exc.retryable:
                    failure_category = exc.category
                    failed_queries += 1
                    skipped_queries = len(queries) - index
                    stopped_at_query = query
                    stop_reason = "http_412" if exc.category == "rate_limited" else exc.category
                    break
                try:
                    self._pace_bilibili_request()
                    hits.extend(self.source.search(query, per_query))
                    successful_queries += 1
                except DataSourceError as retry_exc:
                    limitations.append(str(retry_exc))
                    failed_queries += 1
                    events.append(DiscoveryEvent(
                        phase="search",
                        status=(
                            "http_412"
                            if retry_exc.category == "rate_limited"
                            else "failed_after_retry"
                        ),
                        query=query,
                        detail=retry_exc.category,
                    ))
                    if not retry_exc.retryable:
                        failure_category = retry_exc.category
                        skipped_queries = len(queries) - index
                        stopped_at_query = query
                        stop_reason = (
                            "http_412"
                            if retry_exc.category == "rate_limited"
                            else retry_exc.category
                        )
                        break
        if successful_queries == 0 and not hits and not direct_resources:
            run_status = "failed"
        elif failed_queries:
            run_status = "partial_success"
        else:
            run_status = "success"
        if run_status == "failed" and failure_category is None:
            failure_category = "upstream"
        candidates = aggregate_candidates(hits)[:max_candidates]
        if stop_reason == "http_412":
            events.append(DiscoveryEvent(
                phase="deep_inspection",
                status="skipped_due_to_circuit_breaker",
            ))
            limitations.append(
                "Candidate preview, metadata, subtitles, comments, and deep inspection were skipped "
                "after HTTP 412. Only pre-circuit-breaker search candidates were retained."
            )
            return DiscoveryReport(
                started_at=started_at,
                completed_at=datetime.now(UTC),
                run_status=run_status,
                requirement=requirement,
                expanded_queries=queries,
                candidates_found=len(candidates),
                deep_inspection_limit=deep_limit,
                successful_queries=successful_queries,
                failed_queries=failed_queries,
                skipped_queries=skipped_queries,
                stopped_at_query=stopped_at_query,
                stop_reason=stop_reason,
                failure_category=failure_category,
                candidates=candidates,
                resources=rank_resources(merge_resource_pool(direct_resources)),
                direct_resources=direct_resources,
                events=events,
                evidence_limitations=limitations,
            )
        scan_count = min(len(candidates), max(8, deep_limit * 3))
        if progress and scan_count:
            progress(f"Ranking {scan_count} candidates with lightweight metadata...")
        ranked_candidates = []
        rejected_candidates = []
        for candidate in candidates[:scan_count]:
            is_seeded = "web_index" in candidate.provenance
            try:
                self._pace_bilibili_request()
                preview = self.source.preview(candidate.webpage_url)
                if not passes_hard_relevance(
                    preview.title,
                    preview.description,
                    requirement,
                ):
                    if is_seeded:
                        events.append(DiscoveryEvent(
                            phase="candidate_filter",
                            status="retained_explicit_candidate",
                            detail=candidate.source_id,
                        ))
                    else:
                        events.append(DiscoveryEvent(
                            phase="candidate_filter",
                            status="rejected",
                            detail=candidate.source_id,
                        ))
                        relevance = preview_relevance(
                            preview.title,
                            preview.description,
                            requirement,
                        )
                        rejected_candidates.append((
                            relevance + min(2.0, candidate.discovery_score / 10),
                            candidate,
                        ))
                        continue
                relevance = preview_relevance(
                    preview.title,
                    preview.description,
                    requirement,
                )
            except DataSourceError as exc:
                if exc.category == "rate_limited":
                    failed_queries += 1
                    failure_category = exc.category
                    stop_reason = "http_412"
                    events.append(DiscoveryEvent(
                        phase="candidate_preview",
                        status="http_412",
                        detail=candidate.source_id,
                    ))
                    events.append(DiscoveryEvent(
                        phase="deep_inspection",
                        status="skipped_due_to_circuit_breaker",
                    ))
                    limitations.append(str(exc))
                    return DiscoveryReport(
                        started_at=started_at,
                        completed_at=datetime.now(UTC),
                        run_status="partial_success" if successful_queries else "failed",
                        requirement=requirement,
                        expanded_queries=queries,
                        candidates_found=len(candidates),
                        deep_inspection_limit=deep_limit,
                        successful_queries=successful_queries,
                        failed_queries=failed_queries,
                        skipped_queries=skipped_queries,
                        stop_reason=stop_reason,
                        failure_category=failure_category,
                        candidates=candidates,
                        resources=rank_resources(merge_resource_pool(direct_resources)),
                        direct_resources=direct_resources,
                        events=events,
                        evidence_limitations=limitations,
                    )
                limitations.append(f"Could not preview {candidate.source_id}: {exc}")
                if is_seeded:
                    ranked_candidates.append((candidate.discovery_score, candidate))
                continue
            except ValueError as exc:
                limitations.append(f"Could not preview {candidate.source_id}: {exc}")
                if is_seeded:
                    ranked_candidates.append((candidate.discovery_score, candidate))
                continue
            preview_links = _resource_locators(preview.description)
            project_links = sum(
                classify_resource(locator)[0] in {"code_repository", "hardware_project"}
                for locator in preview_links
            )
            resource_signal = min(3.0, project_links * 2.0 + bool(preview_links) * 0.5)
            combined = relevance + min(2.0, candidate.discovery_score / 10) + resource_signal
            ranked_candidates.append((combined, candidate))
        ranked_candidates.sort(key=lambda item: (-item[0], -item[1].discovery_score))
        if not ranked_candidates and rejected_candidates:
            rejected_candidates.sort(
                key=lambda item: (-item[0], -item[1].discovery_score),
            )
            ranked_candidates = rejected_candidates[:deep_limit]
            for _, candidate in ranked_candidates:
                events.append(DiscoveryEvent(
                    phase="candidate_filter",
                    status="retained_filter_fallback",
                    detail=candidate.source_id,
                ))
            limitations.append(
                "All previewed candidates missed the strict relevance gate; the highest-ranked "
                "bounded candidates were retained for description, subtitle, and comment evidence."
            )
        shortlist = [item[1] for item in ranked_candidates]
        videos = []
        for index, candidate in enumerate(shortlist[:deep_limit], 1):
            if progress:
                progress(f"Inspecting {index}/{min(deep_limit, len(candidates))}: {candidate.source_id}")
            try:
                self._pace_bilibili_request()
                raw = self.source.fetch(candidate.webpage_url, include_comments=include_comments)
            except DataSourceError as exc:
                if exc.category == "rate_limited":
                    failed_queries += 1
                    failure_category = exc.category
                    stop_reason = "http_412"
                    events.append(DiscoveryEvent(
                        phase="deep_inspection",
                        status="http_412",
                        detail=candidate.source_id,
                    ))
                    limitations.append(str(exc))
                    break
                limitations.append(f"Could not inspect {candidate.source_id}: {exc}")
                continue
            except ValueError as exc:
                limitations.append(f"Could not inspect {candidate.source_id}: {exc}")
                continue
            resources = extract_resources(raw)
            inspect_external_resources(resources)
            open_status, open_reason = classify_open_source(raw, resources)
            fit_score, fit_reason = suitability(raw, requirement, resources)
            evidence_basis = ["metadata", "description"]
            if raw.comments:
                evidence_basis.append(f"top_comments:{len(raw.comments)}")
            if raw.subtitles:
                evidence_basis.append(f"subtitle_tracks:{len(raw.subtitles)}")
            evidence_limits = list(raw.warnings)
            if not raw.subtitles:
                evidence_limits.append("No subtitle text was available; the full video was not watched.")
            videos.append(DiscoveredVideo(
                bvid=raw.metadata.bvid,
                title=raw.metadata.title,
                webpage_url=raw.metadata.webpage_url,
                author=raw.metadata.author,
                views=raw.metadata.views,
                likes=raw.metadata.likes,
                duration_seconds=raw.metadata.duration_seconds,
                matched_queries=candidate.matched_queries,
                discovery_score=candidate.discovery_score,
                suitability_score=fit_score,
                suitability_reason=fit_reason,
                open_source_status=open_status,
                open_source_reason=open_reason,
                resources=resources,
                evidence_basis=evidence_basis,
                evidence_limitations=evidence_limits,
            ))
            events.append(DiscoveryEvent(
                phase="deep_inspection",
                status="success",
                detail=candidate.source_id,
            ))
        videos.sort(key=lambda item: (
            -sum(
                resource.kind in {"code_repository", "hardware_project"}
                for resource in item.resources
            ),
            -item.suitability_score,
            -item.discovery_score,
        ))
        resource_pool = merge_resource_pool(
            direct_resources,
            *(video.resources for video in videos),
        )
        inspect_external_resources(resource_pool)
        ranked_resources = rank_resources(resource_pool)
        if stop_reason == "http_412":
            run_status = "partial_success" if successful_queries or videos else "failed"
        return DiscoveryReport(
            started_at=started_at,
            completed_at=datetime.now(UTC),
            run_status=run_status,
            requirement=requirement,
            expanded_queries=queries,
            candidates_found=len(candidates),
            deep_inspection_limit=deep_limit,
            successful_queries=successful_queries,
            failed_queries=failed_queries,
            skipped_queries=skipped_queries,
            stopped_at_query=stopped_at_query,
            stop_reason=stop_reason,
            failure_category=failure_category,
            candidates=candidates,
            videos=videos,
            resources=ranked_resources,
            direct_resources=direct_resources,
            events=events,
            evidence_limitations=limitations,
        )
