import json
from pathlib import Path

from bhka.v1.cli import _seed_candidates, build_parser, infer_mode, main
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


def test_host_video_candidates_accept_numeric_av_and_bv_urls():
    candidates = _seed_candidates(
        ["116136268144356", "https://www.bilibili.com/video/BV1At421h7Ui"]
    )

    assert [item.canonical_id for item in candidates] == [
        "av116136268144356",
        "BV1At421h7Ui",
    ]


def test_external_resource_only_run_uses_no_bilibili_or_external_requests(tmp_path, capsys):
    exit_code = main(
        [
            "discover",
            "寻找 STM32 PCB 开源工程",
            "--mode",
            "resource",
            "--verification",
            "none",
            "--no-bilibili-search",
            "--resource-url",
            "https://github.com/acme/board",
            "--project-root",
            str(tmp_path),
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["counts"]["resources"] == 1
    assert payload["budget"]["bilibili_requests_used"] == 0
    assert payload["budget"]["external_requests_used"] == 0
    report = json.loads(Path(payload["paths"]["json"]).read_text(encoding="utf-8"))
    assert any(event["code"] == "bilibili_disabled" for event in report["events"])


def test_mixed_need_exits_with_machine_readable_clarification(capsys):
    exit_code = main(["discover", "我想学习 PCB 并找开源代码"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert payload["error"]["code"] == "mode_clarification_required"
