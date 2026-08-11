from __future__ import annotations

import json
import re
from typing import Protocol

from openai import OpenAI

from .models import (
    CommentValue,
    RawVideoData,
    Recommendation,
    ResourceValue,
    ScoreReason,
    Topic,
    VideoAnalysisSchema,
    VideoRef,
)


class Analyzer(Protocol):
    def analyze(self, raw: RawVideoData) -> VideoAnalysisSchema: ...


RESOURCE_RE = re.compile(r"https?://[^\s<>\]\[)）]+", re.IGNORECASE)
TECH_TERMS = ["stm32", "pid", "dma", "uart", "can", "spi", "i2c", "pwm", "pcb", "freertos", "hal", "寄存器", "编码器"]
PRACTICE_TERMS = ["实测", "调试", "踩坑", "报错", "解决", "示波器", "逻辑分析仪", "移植", "源码", "工程", "原理图", "驱动"]
RESOURCE_TERMS = ["github", "gitee", "源码", "工程文件", "datasheet", "数据手册", "原理图", "pcb", "网盘", "论文"]


def _score(value: float) -> float:
    return round(max(0.0, min(10.0, value)), 1)


class HeuristicAnalyzer:
    """Transparent baseline for plumbing tests; it is not presented as LLM output."""

    def analyze(self, raw: RawVideoData) -> VideoAnalysisSchema:
        meta = raw.metadata
        subtitle = "\n".join(track.text for track in raw.subtitles)
        comments = "\n".join(item.text for item in raw.comments)
        text = f"{meta.title}\n{meta.description}\n{subtitle}\n{comments}".lower()
        tech_hits = [term for term in TECH_TERMS if term in text]
        practice_hits = [term for term in PRACTICE_TERMS if term in text]
        resource_hits = [term for term in RESOURCE_TERMS if term in text]
        resources = list(dict.fromkeys(RESOURCE_RE.findall(text)))
        has_subtitle = bool(raw.subtitles)
        depth = _score(2.5 + 0.55 * len(tech_hits) + (1.2 if has_subtitle else 0))
        engineering = _score(2 + 0.7 * len(practice_hits) + 0.25 * len(tech_hits))
        resource_value = _score(1.5 + 1.0 * len(resource_hits) + 0.5 * len(resources))
        density = _score(2.5 + 0.45 * len(tech_hits) + min(len(subtitle) / 5000, 2.5))
        practical = _score((engineering * 0.7) + (resource_value * 0.3))
        views = meta.views or 0
        specificity = min(len(tech_hits) * 0.7 + len(practice_hits) * 0.5, 6)
        hidden = _score(2.0 + specificity + (1.5 if 0 < views < 10_000 else 0))
        limitations = ["Heuristic baseline; no semantic LLM judgment was run."]
        if not has_subtitle:
            limitations.append("No subtitle evidence was available.")
        if not raw.comments:
            limitations.append("No comment evidence was available.")
        if meta.favorites is None or meta.coins is None:
            limitations.append("Favorites/coins are not exposed by the selected adapter.")
        content_type = []
        if practice_hits:
            content_type.append("engineering_practice")
        if resource_hits:
            content_type.append("resource_sharing")
        if any(word in text for word in ["教程", "入门", "教学", "课程"]):
            content_type.append("tutorial")
        recommendation_score = _score((depth + engineering + practical + density) / 4)
        reason = "、".join((practice_hits + tech_hits)[:6]) or "标题与简介中的技术信号有限"
        return VideoAnalysisSchema(
            analysis_method="heuristic_baseline",
            evidence_limitations=limitations,
            video=VideoRef(bvid=meta.bvid, title=meta.title),
            topic=Topic(main_topic="STM32" if "stm32" in text else "技术视频", sub_topics=tech_hits),
            content_type=content_type,
            difficulty=ScoreReason(score=depth, reason=f"检测到技术概念：{reason}"),
            technical_depth=ScoreReason(score=depth, reason=f"独立技术信号 {len(tech_hits)} 个；字幕可用={has_subtitle}"),
            engineering_value=ScoreReason(score=engineering, reason=f"工程实践信号：{practice_hits or ['未发现']}"),
            practical_value=ScoreReason(score=practical, reason="依据工程实践和配套资源信号生成的基线估计"),
            resource_value=ResourceValue(score=resource_value, resources=resources + resource_hits),
            comment_value=CommentValue(score=_score(1 + len(raw.comments) * 0.2), observations=[c.text for c in raw.comments[:5]]),
            knowledge_density=ScoreReason(score=density, reason=f"技术信号 {len(tech_hits)} 个，字幕字符 {len(subtitle)}"),
            possible_hidden_value=ScoreReason(score=hidden, reason="实验性独立维度；参考具体性与低播放信号，不是最终公式"),
            important_knowledge=tech_hits + practice_hits,
            target_audience=["嵌入式开发者", "STM32 学习者"] if "stm32" in text else ["技术学习者"],
            recommendation=Recommendation(score=recommendation_score, should_watch=recommendation_score >= 5.5, reason=reason),
        )


class OpenAIAnalyzer:
    def __init__(self, api_key: str, model: str):
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def analyze(self, raw: RawVideoData) -> VideoAnalysisSchema:
        evidence = raw.model_dump(mode="json")
        schema = VideoAnalysisSchema.model_json_schema()
        response = self.client.responses.create(
            model=self.model,
            store=False,
            instructions=(
                "You evaluate Chinese technical videos. Use only supplied evidence. "
                "Separate each 0-10 dimension; do not invent resources or combine a final hidden-value formula. "
                "Set analysis_method to openai_llm and explicitly list missing evidence."
            ),
            input=json.dumps(evidence, ensure_ascii=False),
            text={"format": {"type": "json_schema", "name": "video_analysis", "schema": schema, "strict": False}},
        )
        return VideoAnalysisSchema.model_validate_json(response.output_text)


class DeepSeekAnalyzer:
    """DeepSeek V4 adapter using its OpenAI-compatible JSON Output API."""

    def __init__(self, api_key: str, model: str, base_url: str):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    def analyze(self, raw: RawVideoData) -> VideoAnalysisSchema:
        evidence = raw.model_dump(mode="json")
        schema = VideoAnalysisSchema.model_json_schema()
        system_prompt = (
            "You evaluate Chinese technical videos using only supplied evidence. "
            "Return one valid JSON object matching the provided JSON Schema. "
            "Separate every 0-10 dimension, do not invent resources, and do not create a final "
            "hidden-value formula. Set analysis_method to deepseek_v4_pro and list missing evidence. "
            f"JSON Schema: {json.dumps(schema, ensure_ascii=False)}"
        )
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(evidence, ensure_ascii=False)},
            ],
            response_format={"type": "json_object"},
            max_tokens=8000,
        )
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("DeepSeek returned empty JSON content")
        return VideoAnalysisSchema.model_validate_json(content)
