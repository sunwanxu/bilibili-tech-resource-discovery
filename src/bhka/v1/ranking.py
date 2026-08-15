from __future__ import annotations

import re
from collections.abc import Iterable

from .contracts import DiscoveryCandidate, DiscoveryMode, IntentProfile

_LATIN_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[-_.][a-z0-9]+)*", re.IGNORECASE)
_CJK_CHUNK_RE = re.compile(r"[\u3400-\u9fff]+")
_LEARNING_MARKERS = ("教程", "入门", "从零", "实战", "原理", "详解", "系列", "全流程")
_RESOURCE_MARKERS = (
    "开源",
    "源码",
    "代码",
    "工程",
    "项目",
    "github",
    "gitee",
    "立创",
    "资料",
    "文件",
)


def _terms(value: str) -> set[str]:
    normalized = value.casefold()
    terms = {match.group(0) for match in _LATIN_TOKEN_RE.finditer(normalized)}
    for chunk in _CJK_CHUNK_RE.findall(normalized):
        if len(chunk) <= 4:
            terms.add(chunk)
        for size in (2, 3):
            terms.update(chunk[index : index + size] for index in range(len(chunk) - size + 1))
    return {term for term in terms if term.strip()}


def _similarity(left: DiscoveryCandidate, right: DiscoveryCandidate) -> float:
    left_terms = _terms(f"{left.title} {left.summary}")
    right_terms = _terms(f"{right.title} {right.summary}")
    if not left_terms or not right_terms:
        return 0
    return len(left_terms & right_terms) / len(left_terms | right_terms)


class DeterministicCandidateRanker:
    """Local explainable ranking with soft diversity penalties and no hard rejection."""

    def rank(
        self,
        intent: IntentProfile,
        candidates: Iterable[DiscoveryCandidate],
    ) -> list[DiscoveryCandidate]:
        goal_terms = _terms(
            " ".join([intent.goal, intent.original_request, *intent.constraints])
        )
        scored: list[DiscoveryCandidate] = []
        markers = _LEARNING_MARKERS if intent.mode == DiscoveryMode.LEARNING else _RESOURCE_MARKERS
        for original in candidates:
            candidate = original.model_copy(deep=True)
            title_terms = _terms(candidate.title)
            summary_terms = _terms(candidate.summary)
            title_overlap = goal_terms & title_terms
            summary_overlap = goal_terms & summary_terms
            score = len(title_overlap) * 4 + len(summary_overlap) * 1.5
            reasons = []
            if title_overlap:
                reasons.append(f"title_overlap:{','.join(sorted(title_overlap)[:5])}")
            if summary_overlap:
                reasons.append(f"summary_overlap:{','.join(sorted(summary_overlap)[:5])}")
            marker_hits = [marker for marker in markers if marker in candidate.title.casefold()]
            if marker_hits:
                score += min(4, len(marker_hits) * 1.5)
                reasons.append(f"mode_markers:{','.join(marker_hits[:4])}")
            if len(candidate.provenance) > 1:
                score += min(2, (len(candidate.provenance) - 1) * 0.5)
                reasons.append("multiple_discovery_sources")
            if not candidate.title:
                score -= 3
                reasons.append("missing_title")
            if not title_overlap and not summary_overlap:
                reasons.append("weak_text_overlap")
            candidate.local_score = round(score, 3)
            candidate.local_score_reasons = reasons
            scored.append(candidate)

        remaining = sorted(scored, key=lambda item: (-item.local_score, item.canonical_id))
        selected: list[DiscoveryCandidate] = []
        creator_counts: dict[str, int] = {}
        while remaining:
            best_index = 0
            best_adjusted = float("-inf")
            for index, candidate in enumerate(remaining):
                similarity_penalty = max(
                    (_similarity(candidate, prior) for prior in selected),
                    default=0,
                ) * 3
                creator_key = (candidate.creator_name or "").casefold()
                creator_penalty = max(0, creator_counts.get(creator_key, 0) - 1) * 2 if creator_key else 0
                adjusted = candidate.local_score - similarity_penalty - creator_penalty
                if adjusted > best_adjusted:
                    best_adjusted = adjusted
                    best_index = index
            chosen = remaining.pop(best_index)
            if selected and best_adjusted < chosen.local_score:
                chosen.local_score_reasons.append("diversity_adjusted_order")
            selected.append(chosen)
            if chosen.creator_name:
                creator_key = chosen.creator_name.casefold()
                creator_counts[creator_key] = creator_counts.get(creator_key, 0) + 1
        return selected

