from __future__ import annotations

import re
from collections.abc import Iterable

from .contracts import (
    Breadth,
    DiscoveryMode,
    IntentProfile,
    QueryPlan,
    QuerySpec,
    ResourceSearchStyle,
)

_RESOURCE_INTENT_WORDS = (
    "开源代码",
    "开源资料",
    "项目资料",
    "设计方案",
    "不同技术路线",
    "搜索",
    "寻找",
    "开源",
    "灵感",
    "源码",
    "资源",
    "资料",
)
_LEARNING_INTENT_WORDS = (
    "适合我的能力",
    "中文教程",
    "学习路线",
    "怎么学",
    "如何学习",
    "学习",
)


def _normalized_query(value: str) -> str:
    return " ".join(value.strip().split())


def _base_topic(intent: IntentProfile) -> str:
    value = intent.goal or intent.original_request
    if intent.mode == DiscoveryMode.BOTH:
        removable = (*_RESOURCE_INTENT_WORDS, *_LEARNING_INTENT_WORDS)
    elif intent.mode == DiscoveryMode.RESOURCE:
        removable = _RESOURCE_INTENT_WORDS
    else:
        removable = _LEARNING_INTENT_WORDS
    for phrase in removable:
        value = value.replace(phrase, " ")
    value = re.sub(r"\s+", " ", value).strip(" ，,。")
    return value or _normalized_query(intent.original_request)


class StableQueryPlanner:
    """Small deterministic fallback; host-AI plans can replace it without changing the pipeline."""

    def __init__(
        self,
        *,
        explicit_queries: Iterable[str] = (),
        candidate_target: int | None = None,
        selected_target: int | None = None,
        deep_read_target: int | None = None,
    ):
        self.explicit_queries = [
            normalized
            for item in explicit_queries
            if (normalized := _normalized_query(item))
        ]
        self.candidate_target = candidate_target
        self.selected_target = selected_target
        self.deep_read_target = deep_read_target

    def plan(self, intent: IntentProfile) -> QueryPlan:
        if self.explicit_queries:
            texts = list(dict.fromkeys(self.explicit_queries))[:4]
        else:
            topic = _base_topic(intent)
            texts = [topic]
            if intent.breadth != Breadth.FAST:
                suffix = {
                    DiscoveryMode.LEARNING: "教程 实战",
                    DiscoveryMode.RESOURCE: "开源 源码 工程",
                    DiscoveryMode.BOTH: "教程 开源 工程",
                }[intent.mode]
                texts.append(f"{topic} {suffix}")
            if intent.breadth == Breadth.DEEP:
                suffix = {
                    DiscoveryMode.LEARNING: "系列 全流程",
                    DiscoveryMode.RESOURCE: "项目资料 设计方案",
                    DiscoveryMode.BOTH: "学习路线 项目资料 设计方案",
                }[intent.mode]
                texts.append(f"{topic} {suffix}")
        defaults = {
            Breadth.FAST: (12, 5, 2),
            Breadth.STANDARD: (25, 8, 3),
            Breadth.DEEP: (45, 12, 6),
        }
        candidate_target, selected_target, deep_read_target = defaults[intent.breadth]
        if intent.resource_search_style == ResourceSearchStyle.INSPIRATION:
            candidate_target = max(candidate_target, 60)
            selected_target = max(selected_target, 15)
            deep_read_target = min(deep_read_target, 3)
        if intent.desired_resource_count is not None:
            candidate_target = min(80, max(candidate_target, intent.desired_resource_count * 3))
            selected_target = min(20, max(selected_target, intent.desired_resource_count))
        return QueryPlan(
            queries=[
                QuerySpec(
                    text=text,
                    purpose="precise" if index == 0 else "progressive_expansion",
                    priority=index + 1,
                )
                for index, text in enumerate(texts)
            ],
            candidate_target=self.candidate_target or candidate_target,
            selected_target=self.selected_target or selected_target,
            deep_read_target=(
                self.deep_read_target
                if self.deep_read_target is not None
                else deep_read_target
            ),
        )
