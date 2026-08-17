from bhka.v1.contracts import (
    Breadth,
    DiscoveryMode,
    IntentProfile,
    ResourceSearchStyle,
)
from bhka.v1.planner import StableQueryPlanner


def intent(goal, *, mode=DiscoveryMode.RESOURCE, breadth=Breadth.STANDARD):
    return IntentProfile(
        original_request=goal,
        goal=goal,
        mode=mode,
        breadth=breadth,
    )


def test_default_plan_is_progressive_and_keeps_high_information_entities():
    plan = StableQueryPlanner().plan(intent("2025 电赛 K题 STM32F103C8T6 小车 开源资料"))

    assert len(plan.queries) == 2
    assert plan.queries[0].text == "2025 电赛 K题 STM32F103C8T6 小车"
    for anchor in ("2025", "K题", "STM32F103C8T6", "小车"):
        assert anchor in plan.queries[0].text


def test_explicit_host_ai_queries_win_without_hidden_rewriting():
    plan = StableQueryPlanner(
        explicit_queries=["精确查询", "替代路线", "精确查询"],
        deep_read_target=0,
    ).plan(intent("任意需求"))

    assert [query.text for query in plan.queries] == ["精确查询", "替代路线"]
    assert plan.deep_read_target == 0


def test_resolved_technical_route_is_kept_in_fallback_queries():
    request = intent("我要搭建云台")
    request.constraints = ["无刷电机方案", "双轴", "优先平滑拍摄"]

    plan = StableQueryPlanner().plan(request)

    assert plan.queries[0].text == "我要搭建云台 无刷电机方案 双轴 优先平滑拍摄"
    assert "无刷电机方案" in plan.queries[1].text


def test_fast_learning_mode_sends_one_query_and_reads_two_videos():
    plan = StableQueryPlanner().plan(
        intent("KiCad PCB 中文教程", mode=DiscoveryMode.LEARNING, breadth=Breadth.FAST)
    )

    assert len(plan.queries) == 1
    assert plan.deep_read_target == 2


def test_both_inspiration_mode_expands_breadth_without_deep_reading_everything():
    request = intent("学习 STM32 PCB 并寻找开源设计灵感", mode=DiscoveryMode.BOTH)
    request.resource_search_style = ResourceSearchStyle.INSPIRATION
    request.desired_resource_count = 30

    plan = StableQueryPlanner().plan(request)

    assert plan.candidate_target == 80
    assert plan.selected_target == 20
    assert plan.deep_read_target == 3
    assert "教程 开源 工程" in plan.queries[1].text
