from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from .models import DiscoveryReport, PartSelection, RawVideoData, VideoAnalysisSchema

COOLDOWN_MINUTES = (5, 15, 30)
COOLDOWN_ESCALATION_WINDOW = timedelta(hours=6)


class FileStorage:
    def __init__(self, root: Path):
        self.root = root

    def save_raw(self, raw: RawVideoData) -> Path:
        if raw.metadata.part_number is None:
            path = self.root / "data" / "raw" / f"{raw.metadata.bvid}.json"
        else:
            path = (
                self.root
                / "data"
                / "raw_parts"
                / raw.metadata.bvid
                / f"p{raw.metadata.part_number:03d}.json"
            )
        value = raw.model_dump(mode="json")
        value["metadata"].pop("author", None)
        for comment in value["comments"]:
            comment.pop("author", None)
        self._write_json(path, value)
        return path

    def save_sample_manifest(
        self,
        bvid: str,
        total_parts: int,
        selections: list[PartSelection],
        raw_paths: list[Path],
    ) -> Path:
        path = self.root / "data" / "samples" / f"{bvid}.json"
        value = {
            "bvid": bvid,
            "total_parts": total_parts,
            "strategy": "semantic_roles_then_even_coverage_v1",
            "selections": [
                {
                    **selection.model_dump(mode="json"),
                    "raw_path": str(raw_path.relative_to(self.root)),
                }
                for selection, raw_path in zip(selections, raw_paths, strict=True)
            ],
        }
        self._write_json(path, value)
        return path

    def save_analysis(self, analysis: VideoAnalysisSchema) -> tuple[Path, Path]:
        bvid = analysis.video.bvid
        json_path = self.root / "data" / "processed" / f"{bvid}.json"
        report_path = self.root / "reports" / f"{bvid}.md"
        self._write_json(json_path, analysis.model_dump(mode="json"))
        self._write_text_atomic(report_path, render_markdown(analysis))
        return json_path, report_path

    def save_discovery(self, report: DiscoveryReport) -> tuple[Path, Path]:
        readable = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", report.requirement).strip("-")
        digest = hashlib.sha256(report.requirement.encode("utf-8")).hexdigest()[:8]
        stem = f"{readable[:48] or 'search'}-{digest}"
        json_dir = self.root / "data" / "discovery" / stem
        report_dir = self.root / "reports" / "discovery" / stem
        json_path = json_dir / f"{report.run_id}.json"
        report_path = report_dir / f"{report.run_id}.md"
        json_value = report.model_dump(mode="json")
        markdown = render_discovery_markdown(report)
        self._write_json(json_path, json_value)
        self._write_text_atomic(report_path, markdown)
        if report.run_status != "failed":
            self._write_json(json_dir / "latest.json", json_value)
            self._write_text_atomic(report_dir / "latest.md", markdown)
        if report.stop_reason == "http_412":
            last_412 = report.completed_at.astimezone(UTC)
            state_path = self.root / "data" / "state" / "bilibili_cooldown.json"
            previous_count = 0
            if state_path.is_file():
                try:
                    previous = json.loads(state_path.read_text(encoding="utf-8"))
                    previous_at = datetime.fromisoformat(previous["last_http_412_at"])
                    if previous_at.tzinfo is None:
                        previous_at = previous_at.replace(tzinfo=UTC)
                    elapsed = last_412 - previous_at.astimezone(UTC)
                    if timedelta(0) <= elapsed <= COOLDOWN_ESCALATION_WINDOW:
                        previous_count = max(
                            1,
                            int(previous.get("consecutive_412_count", 1)),
                        )
                except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                    previous_count = 0
            count = min(len(COOLDOWN_MINUTES), previous_count + 1)
            cooldown_minutes = COOLDOWN_MINUTES[count - 1]
            self._write_json(
                state_path,
                {
                    "last_http_412_at": last_412.isoformat(),
                    "cooldown_state": "recommended",
                    "recommended_not_before": (
                        last_412 + timedelta(minutes=cooldown_minutes)
                    ).isoformat(),
                    "cooldown_reason": "risk_control",
                    "official_duration_known": False,
                    "cooldown_policy": "adaptive_5_15_30",
                    "cooldown_minutes": cooldown_minutes,
                    "consecutive_412_count": count,
                    "escalation_window_hours": 6,
                },
            )
        return json_path, report_path

    def active_cooldown(self, now: datetime | None = None) -> dict | None:
        path = self.root / "data" / "state" / "bilibili_cooldown.json"
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            last_412 = datetime.fromisoformat(value["last_http_412_at"])
            if last_412.tzinfo is None:
                last_412 = last_412.replace(tzinfo=UTC)
            last_412 = last_412.astimezone(UTC)
            count = max(1, min(
                len(COOLDOWN_MINUTES),
                int(value.get("consecutive_412_count", 1)),
            ))
            cooldown_minutes = COOLDOWN_MINUTES[count - 1]
            # Derive the deadline from the event and policy instead of trusting
            # a possibly stale or inconsistent stored deadline.
            not_before = last_412 + timedelta(minutes=cooldown_minutes)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return None
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        current = current.astimezone(UTC)
        if last_412 > current + timedelta(minutes=5):
            path.unlink(missing_ok=True)
            return None
        if current >= not_before:
            path.unlink(missing_ok=True)
            return None
        value.update({
            "cooldown_policy": "adaptive_5_15_30",
            "cooldown_minutes": cooldown_minutes,
            "consecutive_412_count": count,
            "escalation_window_hours": 6,
            "recommended_not_before": not_before.isoformat(),
        })
        return value

    @staticmethod
    def _write_json(path: Path, value: dict) -> None:
        FileStorage._write_text_atomic(
            path,
            json.dumps(value, ensure_ascii=False, indent=2),
        )

    @staticmethod
    def _write_text_atomic(path: Path, value: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(value, encoding="utf-8")
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()


def render_markdown(a: VideoAnalysisSchema) -> str:
    limitations = "\n".join(f"- {item}" for item in a.evidence_limitations) or "- 无"
    resources = "\n".join(f"- {item}" for item in a.resource_value.resources) or "- 未发现"
    knowledge = "\n".join(f"- {item}" for item in a.important_knowledge) or "- 未识别"
    return f"""# {a.video.title}

- BVID：{a.video.bvid}
- 分析方法：{a.analysis_method}
- 技术深度：{a.technical_depth.score}/10
- 工程价值：{a.engineering_value.score}/10
- 实践价值：{a.practical_value.score}/10
- 可能的隐藏价值：{a.possible_hidden_value.score}/10
- 推荐分：{a.recommendation.score}/10

## 为什么值得看

{a.recommendation.reason}

## 重要知识

{knowledge}

## 资源信号

{resources}

## 证据限制

{limitations}
"""


def render_discovery_markdown(report: DiscoveryReport) -> str:
    query_lines = "\n".join(f"- {query}" for query in report.expanded_queries)
    candidate_lines = "\n".join(
        f"- [{item.source_id}]({item.webpage_url}) — "
        f"queries: {', '.join(item.matched_queries)}; "
        f"sources: {', '.join(item.provenance) or 'unknown'}"
        for item in report.candidates
    ) or "- None"
    resource_blocks = []
    for index, item in enumerate(report.resources, 1):
        artifacts = ", ".join(
            f"{name}={status}" for name, status in item.artifacts.items()
        ) or "not inspected"
        videos = ", ".join(item.supporting_videos) or "none"
        origins = ", ".join(item.origins or [item.origin])
        resource_blocks.append(
            f"### {index}. [{item.kind}]({item.locator})\n\n"
            f"- Resource value: {item.resource_score}/10\n"
            f"- Usability: {item.usability_status}\n"
            f"- Why useful: {item.resource_value_reason}\n"
            f"- License: {item.license_status}\n"
            f"- Access: {item.access_status}\n"
            f"- Inspection: {item.inspection_status}\n"
            f"- Artifacts: {artifacts}\n"
            f"- Evidence origins: {origins}\n"
            f"- Supporting Bilibili videos: {videos}"
        )
    primary_resource_lines = "\n\n".join(resource_blocks) or "- None"
    event_lines = "\n".join(
        f"- {item.timestamp.isoformat()} | {item.phase} | {item.status}"
        + (f" | {item.query}" if item.query else "")
        + (f" | {item.detail}" if item.detail else "")
        for item in report.events
    ) or "- None"
    sections = []
    for index, video in enumerate(report.videos, 1):
        resource_blocks = []
        for resource in video.resources:
            artifact_text = ", ".join(
                f"{name}={status}" for name, status in resource.artifacts.items()
            ) or "未检查内容完整度"
            notes = "; ".join(resource.verification_notes) or "无附加说明"
            resource_blocks.append(
                f"  - {resource.kind}: {resource.locator}\n"
                f"    - 来源：{resource.origin}\n"
                f"    - 访问：{resource.access_status}\n"
                f"    - 检查：{resource.inspection_status}\n"
                f"    - 许可：{resource.license_status}\n"
                f"    - 内容：{artifact_text}\n"
                f"    - 说明：{notes}"
            )
        resource_lines = "\n".join(resource_blocks) or "  - 未发现外部资源链接"
        limitation_lines = "\n".join(
            f"  - {item}" for item in video.evidence_limitations
        ) or "  - 无"
        sections.append(f"""## {index}. [{video.title}]({video.webpage_url})

- BVID：{video.bvid}
- 作者：{video.author or '未知'}
- 适合度：{video.suitability_score}/10
- 适合度依据：{video.suitability_reason}
- 开源状态：{video.open_source_status}
- 开源判断：{video.open_source_reason}
- 证据范围：{', '.join(video.evidence_basis)}
- 命中查询：{'; '.join(video.matched_queries)}

### 外部资源

{resource_lines}

### 证据限制

{limitation_lines}
""")
    global_limits = "\n".join(f"- {item}" for item in report.evidence_limitations) or "- 无"
    return f"""# B站技术资源发现报告

## 用户需求

{report.requirement}

## 查询扩展

{query_lines}

## 搜索概况

- 运行 ID：{report.run_id}
- 运行状态：{report.run_status}
- 成功查询：{report.successful_queries}
- 失败查询：{report.failed_queries}
- 跳过查询：{report.skipped_queries}
- 停止查询：{report.stopped_at_query or '无'}
- 停止原因：{report.stop_reason or '无'}
- 失败分类：{report.failure_category or '无'}
- 去重候选数：{report.candidates_found}
- 深读上限：{report.deep_inspection_limit}
- 实际深读成功：{len(report.videos)}

## 搜索候选（包含熔断前保留项）

{candidate_lines}

## 运行事件

{event_lines}

## Primary usable project resources

{primary_resource_lines}

## Supporting Bilibili videos

{''.join(sections)}
## 全局证据限制

{global_limits}
"""
