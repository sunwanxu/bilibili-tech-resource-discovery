from bhka.v1.contracts import Breadth, DiscoveryMode, IntentProfile
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


def test_fast_learning_mode_sends_one_query_and_reads_two_videos():
    plan = StableQueryPlanner().plan(
        intent("KiCad PCB 中文教程", mode=DiscoveryMode.LEARNING, breadth=Breadth.FAST)
    )

    assert len(plan.queries) == 1
    assert plan.deep_read_target == 2

