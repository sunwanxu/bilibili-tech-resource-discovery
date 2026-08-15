#!/usr/bin/env python3
"""Install this local Skill into Codex without copying caches or credentials."""

from __future__ import annotations

import argparse
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

SKILL_NAME = "bilibili-tech-resource-discovery"
REQUIRED_FILES = (
    "SKILL.md",
    "agents/openai.yaml",
    "references/onboarding.md",
    "references/evidence-standard.md",
    "scripts/onboard.py",
    "scripts/install.py",
    "scripts/install_skill.py",
    "runtime/pyproject.toml",
    "runtime/src/bhka/cli.py",
    "runtime/src/bhka/v1/cli.py",
)


def is_project_root(path: Path) -> bool:
    pyproject = path / "pyproject.toml"
    return pyproject.is_file() and 'name = "bilibili-hidden-knowledge-agent"' in pyproject.read_text(
        encoding="utf-8"
    )


def default_target_root() -> Path:
    configured = os.getenv("CODEX_HOME", "").strip()
    return Path(configured).expanduser() / "skills" if configured else Path.home() / ".codex" / "skills"


def validate_skill(path: Path) -> None:
    missing = [relative for relative in REQUIRED_FILES if not (path / relative).is_file()]
    if missing:
        raise RuntimeError("Skill installation is incomplete: " + ", ".join(missing))


def install_skill(project_root: Path, target_root: Path, force: bool) -> tuple[Path, Path | None]:
    project_root = project_root.expanduser().resolve()
    if not is_project_root(project_root):
        raise RuntimeError("--project-root is not the bilibili-hidden-knowledge-agent repository.")
    source = project_root / "skills" / SKILL_NAME
    validate_skill(source)
    target_root = target_root.expanduser().resolve()
    target_root.mkdir(parents=True, exist_ok=True)
    target = target_root / SKILL_NAME
    if source.resolve() == target.resolve():
        (target / ".project-root").write_text(str(project_root), encoding="utf-8")
        return target, None
    if target.exists() and not force:
        raise RuntimeError(f"Skill already exists at {target}. Re-run with --force to update it safely.")

    staging = target_root / f".{SKILL_NAME}.install-{uuid4().hex}"
    shutil.copytree(
        source,
        staging,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".project-root"),
    )
    (staging / ".project-root").write_text(str(project_root), encoding="utf-8")
    validate_skill(staging)

    backup: Path | None = None
    try:
        if target.exists():
            stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
            backup_root = target_root.parent / "skill-backups"
            backup_root.mkdir(parents=True, exist_ok=True)
            backup = backup_root / f"{SKILL_NAME}.backup-{stamp}"
            if backup.exists():
                backup = backup_root / f"{SKILL_NAME}.backup-{stamp}-{uuid4().hex[:6]}"
            os.replace(target, backup)
        os.replace(staging, target)
    except Exception:
        if backup and backup.exists() and not target.exists():
            os.replace(backup, target)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    validate_skill(target)
    return target, backup


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--target-root", type=Path, default=default_target_root())
    parser.add_argument("--force", action="store_true", help="update an existing installation")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        target, backup = install_skill(args.project_root, args.target_root, args.force)
    except (OSError, RuntimeError) as exc:
        print(f"Installation failed: {exc}")
        return 2
    print(f"Skill installed: {target}")
    if backup:
        print(f"Previous installation backed up: {backup}")
    print("Restart or open a new Codex task, then invoke $bilibili-tech-resource-discovery.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
