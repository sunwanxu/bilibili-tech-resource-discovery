import pytest
from pydantic import ValidationError

from bhka.v1.contracts import (
    Breadth,
    DiscoveryMode,
    IntentProfile,
    NetworkBudget,
    QueryPlan,
    QuerySpec,
    RetentionPolicy,
    VerificationScope,
)


def test_intent_profile_has_stable_user_safe_defaults():
    profile = IntentProfile(
        original_request="我想学习画 STM32 PCB",
        goal="找到适合初学者的 PCB 教程",
        mode=DiscoveryMode.LEARNING,
    )

    assert profile.breadth == Breadth.STANDARD
    assert profile.verification_scope == VerificationScope.CORE
    assert profile.retention == RetentionPolicy.MINIMAL
    assert profile.login_allowed is False


def test_query_plan_is_small_and_progressive():
    plan = QueryPlan(
        queries=[
            QuerySpec(
                text="STM32F103C8T6 最小系统 PCB 教程",
                purpose="精确教程",
                required_anchors=["STM32F103C8T6", "PCB"],
            )
        ]
    )

    assert len(plan.queries) == 1
    assert plan.candidate_target == 20
    assert plan.deep_read_target < plan.candidate_target


def test_query_plan_rejects_invalid_target_order():
    with pytest.raises(ValidationError):
        QueryPlan(
            queries=[QuerySpec(text="test", purpose="test")],
            candidate_target=5,
            selected_target=6,
            deep_read_target=1,
        )


def test_http_412_opens_one_run_wide_circuit():
    budget = NetworkBudget(bilibili_requests_limit=3)
    budget.consume_bilibili()
    budget.open_circuit("http_412")

    assert budget.bilibili_requests_used == 1
    assert budget.allow_bilibili() is False
    assert budget.circuit_reason == "http_412"
    with pytest.raises(RuntimeError):
        budget.consume_bilibili()

