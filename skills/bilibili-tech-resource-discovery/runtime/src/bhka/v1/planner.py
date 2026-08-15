from __future__ import annotations

import re
from collections.abc import Iterable

from .contracts import Breadth, DiscoveryMode, IntentProfile, QueryPlan, QuerySpec

_RESOURCE_INTENT_WORDS = (
    "开源代码",
    "开源资料",
    "项目资料",
    "设计方案",
    "不同技术路线",
    "源码",
    "资源",
)
_LEARNING_INTENT_WORDS = ("适合我的能力", "中文教程", "学习路线", "怎么学", "如何学习")


def _normalized_query(value: str) -> str:
    return " ".join(value.strip().split())


def _base_topic(intent: IntentProfile) -> str:
    value = intent.goal or intent.original_request
    removable = _RESOURCE_INTENT_WORDS if intent.mode == DiscoveryMode.RESOURCE else _LEARNING_INTENT_WORDS
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
                suffix = "教程 实战" if intent.mode == DiscoveryMode.LEARNING else "开源 源码 工程"
                texts.append(f"{topic} {suffix}")
            if intent.breadth == Breadth.DEEP:
                suffix = "系列 全流程" if intent.mode == DiscoveryMode.LEARNING else "项目资料 设计方案"
                texts.append(f"{topic} {suffix}")
        defaults = {
            Breadth.FAST: (12, 5, 2),
            Breadth.STANDARD: (25, 8, 3),
            Breadth.DEEP: (45, 12, 6),
        }
        candidate_target, selected_target, deep_read_target = defaults[intent.breadth]
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

