import json

from bhka.v1.cli import build_parser, infer_mode, main
from bhka.v1.contracts import DiscoveryMode


def test_mode_inference_requires_clarification_for_mixed_need():
    assert infer_mode("我想学 PCB 并找开源工程") is None
    assert infer_mode("我想学习 KiCad") == DiscoveryMode.LEARNING
    assert infer_mode("寻找 STM32 开源代码") == DiscoveryMode.RESOURCE


def test_parser_accepts_plain_natural_language_request():
    args = build_parser().parse_args(["discover", "我想学习 KiCad"])

    assert args.request == "我想学习 KiCad"
    assert args.mode == "auto"
    assert args.breadth == "standard"


def test_parser_exposes_v1_private_login_command():
    args = build_parser().parse_args(["login", "--timeout-minutes", "7"])

    assert args.command == "login"
    assert args.timeout_minutes == 7


def test_parser_allows_user_to_decline_resource_verification():
    args = build_parser().parse_args(
        ["discover", "寻找 PCB 工程", "--verification", "none"]
    )

    assert args.verification == "none"


def test_mixed_need_exits_with_machine_readable_clarification(capsys):
    exit_code = main(["discover", "我想学习 PCB 并找开源代码"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert payload["error"]["code"] == "mode_clarification_required"
