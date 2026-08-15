from bhka.v1.contracts import DiscoveryCandidate, DiscoveryMode, IntentProfile
from bhka.v1.ranking import DeterministicCandidateRanker


def candidate(identifier, title, *, creator=None, provenance=None):
    return DiscoveryCandidate(
        canonical_id=identifier,
        url=f"https://www.bilibili.com/video/{identifier}",
        title=title,
        creator_name=creator,
        provenance=provenance or ["bilibili_search_page"],
    )


def test_resource_mode_ranks_relevant_open_project_above_unrelated_video():
    intent = IntentProfile(
        original_request="我想找 STM32F103C8T6 PCB 开源资料",
        goal="找到 STM32F103C8T6 PCB 开源工程",
        mode=DiscoveryMode.RESOURCE,
    )
    candidates = [
        candidate("BV2", "今日游戏新闻"),
        candidate("BV1", "STM32F103C8T6 最小系统 PCB 开源工程"),
    ]

    ranked = DeterministicCandidateRanker().rank(intent, candidates)

    assert [item.canonical_id for item in ranked] == ["BV1", "BV2"]
    assert ranked[0].local_score > ranked[1].local_score
    assert "weak_text_overlap" in ranked[1].local_score_reasons


def test_ranker_keeps_weak_candidates_and_softly_diversifies_duplicates():
    intent = IntentProfile(
        original_request="学习 KiCad PCB",
        goal="学习 KiCad PCB",
        mode=DiscoveryMode.LEARNING,
    )
    candidates = [
        candidate("BV1", "KiCad PCB 入门教程 第一集", creator="same"),
        candidate("BV2", "KiCad PCB 入门教程 第二集", creator="same"),
        candidate("BV3", "KiCad PCB 实战：画一块最小系统板", creator="other"),
        candidate("BV4", "电子设计闲聊"),
    ]

    ranked = DeterministicCandidateRanker().rank(intent, candidates)

    assert {item.canonical_id for item in ranked} == {"BV1", "BV2", "BV3", "BV4"}
    assert ranked[-1].canonical_id == "BV4"
    assert any("diversity_adjusted_order" in item.local_score_reasons for item in ranked)


def test_model_and_acronym_anchors_outweigh_generic_chinese_overlap():
    intent = IntentProfile(
        original_request="寻找 ESP32-C3 MQTT 智能家居开源代码",
        goal="寻找 ESP32-C3 MQTT 智能家居开源代码",
        mode=DiscoveryMode.RESOURCE,
    )
    candidates = [
        candidate("BV1", "【开源】智能家居配置教程和代码"),
        candidate("BV2", "ESP32C3 使用 MQTT 连接云端实战"),
    ]

    ranked = DeterministicCandidateRanker().rank(intent, candidates)

    assert ranked[0].canonical_id == "BV2"
    assert any(reason.startswith("technical_anchors:") for reason in ranked[0].local_score_reasons)


def test_problem_letter_anchor_ranks_requested_problem_before_other_open_projects():
    intent = IntentProfile(
        original_request="寻找 2025 电赛 K题小车开源方案",
        goal="寻找 2025 电赛 K题小车开源方案",
        mode=DiscoveryMode.RESOURCE,
    )
    candidates = [
        candidate("BV1", "【开源】2025 电赛 E题完整方案"),
        candidate("BV2", "2025 电赛 K题自动避障小车"),
    ]

    ranked = DeterministicCandidateRanker().rank(intent, candidates)

    assert ranked[0].canonical_id == "BV2"
    assert any("problem:k" in reason for reason in ranked[0].local_score_reasons)
