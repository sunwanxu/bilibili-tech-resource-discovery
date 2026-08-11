#!/usr/bin/env python3
"""Install this self-contained Agent Skill for Codex or OpenCode."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tomllib
import venv
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

SKILL_NAME = "bilibili-tech-resource-discovery"
AGENTS = ("codex", "opencode")


def skill_source() -> Path:
    return Path(__file__).resolve().parents[1]


def target_root(agent: str, home: Path | None = None) -> Path:
    home = (home or Path.home()).expanduser()
    if agent == "codex":
        configured = os.getenv("CODEX_HOME", "").strip()
        return Path(configured).expanduser() / "skills" if configured else home / ".codex" / "skills"
    if agent == "opencode":
        return home / ".config" / "opencode" / "skills"
    raise ValueError(f"Unsupported agent: {agent}")


def detect_agents(source: Path, home: Path | None = None) -> list[str]:
    home = (home or Path.home()).expanduser()
    resolved = source.resolve()
    for agent in AGENTS:
        try:
            resolved.relative_to(target_root(agent, home).resolve())
            return [agent]
        except ValueError:
            pass
    detected = [agent for agent in AGENTS if target_root(agent, home).parent.exists()]
    return detected or ["opencode"]


def validate_bundle(source: Path) -> None:
    required = (
        "SKILL.md",
        "references/onboarding.md",
        "references/evidence-standard.md",
        "scripts/install.py",
        "runtime/pyproject.toml",
        "runtime/src/bhka/cli.py",
    )
    missing = [relative for relative in required if not (source / relative).is_file()]
    if missing:
        raise RuntimeError("Skill bundle is incomplete: " + ", ".join(missing))


def _rewrite_managed_cookie_path(runtime: Path) -> None:
    managed_cookie = runtime / ".auth" / "bilibili.cookies.txt"
    env_path = runtime / ".env"
    if managed_cookie.is_file() and env_path.is_file():
        lines = env_path.read_text(encoding="utf-8-sig").splitlines()
        updates = {
            "BILIBILI_COOKIES_FILE": str(managed_cookie.resolve()),
            "BILIBILI_COOKIES_FROM_BROWSER": "",
        }
        output: list[str] = []
        found: set[str] = set()
        for line in lines:
            key = line.split("=", 1)[0].strip() if "=" in line else ""
            if key in updates:
                output.append(f"{key}={updates[key]}")
                found.add(key)
            else:
                output.append(line)
        output.extend(f"{key}={value}" for key, value in updates.items() if key not in found)
        env_path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


def _upgrade_safe_runtime_defaults(runtime: Path) -> None:
    """Upgrade only known historical non-secret defaults in an existing .env."""
    env_path = runtime / ".env"
    if not env_path.is_file():
        return
    replacements = {
        "BILIBILI_RETRIES=2": "BILIBILI_RETRIES=1",
        "BILIBILI_RATE_LIMIT_SECONDS=1.0": "BILIBILI_RATE_LIMIT_SECONDS=2.5",
    }
    lines = env_path.read_text(encoding="utf-8-sig").splitlines()
    updated = [replacements.get(line.strip(), line) for line in lines]
    env_path.write_text("\n".join(updated).rstrip() + "\n", encoding="utf-8")


def _copy_runtime_state(old_runtime: Path, new_runtime: Path) -> None:
    if (old_runtime / ".env").is_file():
        shutil.copy2(old_runtime / ".env", new_runtime / ".env")
    for directory in (".auth", "data", "reports"):
        source = old_runtime / directory
        destination = new_runtime / directory
        if source.is_dir():
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(source, destination)
    _rewrite_managed_cookie_path(new_runtime)
    _upgrade_safe_runtime_defaults(new_runtime)


def _copy_bundle(
    source: Path,
    target: Path,
    force: bool,
    state_from: Path | None = None,
) -> Path | None:
    target_root_path = target.parent
    target_root_path.mkdir(parents=True, exist_ok=True)
    if source.resolve() == target.resolve():
        return None
    if target.exists() and not force:
        raise RuntimeError(f"Skill already exists at {target}; use --force to update it.")
    staging = target_root_path / f".{SKILL_NAME}.install-{uuid4().hex}"
    shutil.copytree(
        source,
        staging,
        ignore=shutil.ignore_patterns(
            "__pycache__",
            "*.pyc",
            "*.pyo",
            ".venv",
            ".env",
            ".auth",
            "data",
            "reports",
            ".pytest_cache",
            ".project-root",
        ),
    )
    existing_runtime = target / "runtime"
    # Migrate legacy project state first, then let a newer installed Skill state
    # take precedence. An empty runtime from an interrupted install must not hide
    # a valid managed login in the legacy project.
    if state_from and state_from.is_dir():
        _copy_runtime_state(state_from, staging / "runtime")
    if existing_runtime.is_dir():
        _copy_runtime_state(existing_runtime, staging / "runtime")
    validate_bundle(staging)
    backup: Path | None = None
    try:
        if target.exists():
            stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
            backup_root = target_root_path.parent / "skill-backups"
            backup_root.mkdir(parents=True, exist_ok=True)
            backup = backup_root / f"{SKILL_NAME}.backup-{stamp}"
            if backup.exists():
                backup = backup_root / f"{SKILL_NAME}.backup-{stamp}-{uuid4().hex[:6]}"
            try:
                os.replace(target, backup)
            except PermissionError:
                # Windows agents may keep a handle open inside the active Skill.
                # Preserve a recoverable copy, then update files in place without
                # asking the user to close the agent application.
                shutil.copytree(target, backup)
                shutil.copytree(staging, target, dirs_exist_ok=True)
                shutil.rmtree(staging)
                staging = target_root_path / f".{SKILL_NAME}.installed-{uuid4().hex}"
        if not target.exists():
            os.replace(staging, target)
        previous_venv = backup / "runtime" / ".venv" if backup else None
        installed_venv = target / "runtime" / ".venv"
        if previous_venv and previous_venv.is_dir() and not installed_venv.exists():
            try:
                os.replace(previous_venv, installed_venv)
            except OSError:
                # A locked environment is safely rebuilt by install_runtime.
                pass
    except Exception:
        if backup and backup.exists() and not target.exists():
            os.replace(backup, target)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    _rewrite_managed_cookie_path(target / "runtime")
    _upgrade_safe_runtime_defaults(target / "runtime")
    return backup


def runtime_paths(runtime: Path) -> tuple[Path, Path]:
    if os.name == "nt":
        scripts = runtime / ".venv" / "Scripts"
        return scripts / "python.exe", scripts / "bhka.exe"
    scripts = runtime / ".venv" / "bin"
    return scripts / "python", scripts / "bhka"


def _managed_login_exists(runtime: Path) -> bool:
    return (runtime / ".auth" / "bilibili.cookies.txt").is_file()


def install_runtime(target: Path, login: bool) -> None:
    runtime = target / "runtime"
    python, bhka = runtime_paths(runtime)
    if not python.is_file():
        venv.EnvBuilder(with_pip=True).create(runtime / ".venv")
    result = subprocess.run(
        [str(python), "-m", "pip", "install", "-e", str(runtime)],
        check=False,
    )
    if result.returncode:
        raise RuntimeError("The bundled Python runtime could not be installed.")
    expected_version = tomllib.loads(
        (runtime / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]["version"]
    verification = subprocess.run(
        [str(bhka), "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    expected_output = f"bhka {expected_version}"
    if verification.returncode or verification.stdout.strip() != expected_output:
        raise RuntimeError(
            "The installed command does not match the bundled runtime version."
        )
    print(f"Runtime verified: {expected_output} ({bhka})")
    if login and not _managed_login_exists(runtime):
        result = subprocess.run(
            [str(bhka), "login", "--project-root", str(runtime)],
            check=False,
        )
        if result.returncode:
            raise RuntimeError("Runtime installed, but Bilibili login was not completed.")


def install(
    agent: str,
    force: bool,
    login: bool,
    home: Path | None = None,
    state_from: Path | None = None,
) -> list[Path]:
    if sys.version_info < (3, 11):  # noqa: UP036
        raise RuntimeError("Python 3.11 or newer is required.")
    source = skill_source()
    validate_bundle(source)
    agents = detect_agents(source, home) if agent == "auto" else list(AGENTS) if agent == "all" else [agent]
    installed: list[Path] = []
    for name in agents:
        target = target_root(name, home) / SKILL_NAME
        backup = _copy_bundle(source, target, force, state_from)
        install_runtime(target, login)
        installed.append(target)
        print(f"Installed for {name}: {target}")
        if backup:
            print(f"Previous installation backed up: {backup}")
    return installed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--agent",
        choices=("auto", "codex", "opencode", "all"),
        default="auto",
        help="target agent; auto detects installed clients",
    )
    parser.add_argument("--force", action="store_true", help="update an existing installation")
    parser.add_argument("--no-login", action="store_true", help="install without opening login")
    parser.add_argument(
        "--state-from",
        type=Path,
        help=argparse.SUPPRESS,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        installed = install(
            args.agent,
            args.force,
            not args.no_login,
            state_from=args.state_from,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Installation failed: {exc}")
        return 2
    print("Installation is complete. Open a new agent session and describe your need naturally.")
    print(f"Installed copies: {len(installed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
