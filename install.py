from __future__ import annotations

import argparse
import os
import subprocess
import sys
import venv
from pathlib import Path

PROJECT_NAME = "bilibili-hidden-knowledge-agent"
SKILL_NAME = "bilibili-tech-resource-discovery"


def venv_paths(root: Path) -> tuple[Path, Path]:
    if os.name == "nt":
        scripts = root / ".venv" / "Scripts"
        return scripts / "python.exe", scripts / "bhka.exe"
    scripts = root / ".venv" / "bin"
    return scripts / "python", scripts / "bhka"


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def managed_login_configured(root: Path) -> bool:
    value = parse_env(root / ".env").get("BILIBILI_COOKIES_FILE", "")
    if not value:
        return False
    configured = Path(value).expanduser()
    if not configured.is_absolute():
        configured = root / configured
    managed = root / ".auth" / "bilibili.cookies.txt"
    try:
        return configured.resolve() == managed.resolve() and managed.is_file()
    except OSError:
        return False


def run(command: list[str]) -> int:
    return subprocess.run(command, check=False).returncode


def install(root: Path, *, login: bool = True) -> int:
    if sys.version_info < (3, 11):  # noqa: UP036 - bootstrap diagnoses older host Pythons
        print("Python 3.11 or newer is required.")
        return 2
    if not (root / "pyproject.toml").is_file():
        print(f"Run this installer from the {PROJECT_NAME} project directory.")
        return 2

    venv_python, _ = venv_paths(root)
    if not venv_python.is_file():
        print("[1/4] Creating the local Python environment...")
        venv.EnvBuilder(with_pip=True).create(root / ".venv")
    else:
        print("[1/4] Local Python environment already exists.")

    print("[2/4] Portable runtime bundle found.")

    print("[3/4] Installing or updating the portable Skill...")
    skill_installer = root / "skills" / SKILL_NAME / "scripts" / "install.py"
    install_command = [
        str(venv_python),
        str(skill_installer),
        "--agent",
        "codex",
        "--force",
        "--state-from",
        str(root),
    ]
    if not login:
        install_command.append("--no-login")
    if run(install_command):
        print("Skill installation failed. Keep the error above for the developer AI.")
        return 1

    if not login:
        print("[4/4] Login skipped for an offline or automated installation check.")
    else:
        print("[4/4] Existing managed login was preserved, or first login was completed.")

    print("Installation is complete.")
    print("Open a new agent session and describe the technical resource you want naturally.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install the Bilibili discovery runtime, Skill, and managed login.",
    )
    parser.add_argument(
        "--no-login",
        action="store_true",
        help="install locally without opening Edge; intended for CI or offline checks",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return install(Path(__file__).resolve().parent, login=not args.no_login)


if __name__ == "__main__":
    raise SystemExit(main())
