from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .contracts import RunOutcome

_SENSITIVE_ATTRIBUTE_PARTS = {
    "authorization",
    "cookie",
    "formats",
    "headers",
    "media_url",
    "request_header",
    "token",
}


@dataclass(frozen=True)
class ReportPaths:
    json_path: Path
    markdown_path: Path
    latest_json_path: Path


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _safe_value(value):
    if isinstance(value, dict):
        return {
            str(key): _safe_value(item)
            for key, item in value.items()
            if not any(part in str(key).casefold() for part in _SENSITIVE_ATTRIBUTE_PARTS)
        }
    if isinstance(value, list):
        return [_safe_value(item) for item in value]
    return value


def _report_payload(outcome: RunOutcome) -> dict[str, object]:
    payload = outcome.model_dump(mode="json")
    evidence_limit = 800 if outcome.intent.retention.value == "minimal" else None
    for record in payload["evidence"]:
        text = record.get("text")
        if evidence_limit is not None and isinstance(text, str):
            record["text"] = text[:evidence_limit]
        record["attributes"] = _safe_value(record.get("attributes", {}))
    return payload


def render_markdown(outcome: RunOutcome) -> str:
    lines = [
        "# B 站技术资源搜索报告",
        "",
        f"- 状态：`{outcome.status}`",
        f"- 模式：`{outcome.intent.mode.value}`",
        f"- 需求：{outcome.intent.original_request}",
        f"- 完整候选：{len(outcome.candidates)}",
        f"- 精选候选：{len(outcome.selected_candidates)}",
        f"- 外部资源：{len(outcome.resources)}",
        "",
        "## 精选视频",
        "",
    ]
    if not outcome.selected_candidates:
        lines.append("本轮没有获得可推荐的视频候选。")
    for index, candidate in enumerate(outcome.selected_candidates, 1):
        lines.extend(
            [
                f"### {index}. {candidate.title or candidate.canonical_id}",
                "",
                f"- 视频：{candidate.url}",
                f"- 本地相关性分：{candidate.local_score:.2f}",
                f"- 依据：{'; '.join(candidate.local_score_reasons) or '待深读'}",
                "",
            ]
        )
    lines.extend(["## 可用资源", ""])
    if not outcome.resources:
        lines.append("本轮尚未从已读证据中提取到外部资源。")
    for resource in outcome.resources:
        lines.extend(
            [
                f"- [{resource.locator}]({resource.locator})",
                f"  - 类型：`{resource.kind.value}`",
                f"  - 访问：`{resource.access_status.value}`",
                f"  - 开源：`{resource.license_status.value}`",
                f"  - 许可证：{resource.license_name or '未验证'}",
            ]
        )
    lines.extend(["", "## 完整候选池", ""])
    for candidate in outcome.candidates:
        lines.append(
            f"- [{candidate.title or candidate.canonical_id}]({candidate.url}) "
            f"— {candidate.local_score:.2f}"
        )
    if outcome.limitations:
        lines.extend(["", "## 证据限制", ""])
        lines.extend(f"- {item}" for item in outcome.limitations)
    return "\n".join(lines).rstrip() + "\n"


class ReportWriter:
    def __init__(self, report_root: Path):
        self.report_root = report_root.resolve()

    def write(self, outcome: RunOutcome) -> ReportPaths:
        run_root = self.report_root / "runs" / outcome.run_id
        json_path = run_root / "report.json"
        markdown_path = run_root / "report.md"
        json_content = json.dumps(
            _report_payload(outcome),
            ensure_ascii=False,
            indent=2,
        )
        _atomic_write(json_path, json_content + "\n")
        _atomic_write(markdown_path, render_markdown(outcome))
        if outcome.status in {"success", "partial_success"}:
            latest_json_path = self.report_root / "latest.json"
        else:
            latest_json_path = self.report_root / "latest-failed.json"
        _atomic_write(latest_json_path, json_content + "\n")
        return ReportPaths(
            json_path=json_path,
            markdown_path=markdown_path,
            latest_json_path=latest_json_path,
        )
