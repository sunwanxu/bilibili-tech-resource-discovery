from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "install.py"
SPEC = importlib.util.spec_from_file_location("project_installer", SCRIPT)
assert SPEC and SPEC.loader
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


def prepare_project(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "bilibili-hidden-knowledge-agent"\n',
        encoding="utf-8",
    )
    skill_installer = (
        tmp_path
        / "skills"
        / installer.SKILL_NAME
        / "scripts"
        / "install.py"
    )
    skill_installer.parent.mkdir(parents=True)
    skill_installer.touch()
    python = tmp_path / "python"
    bhka = tmp_path / "bhka"
    python.touch()
    bhka.touch()
    monkeypatch.setattr(installer, "venv_paths", lambda root: (python, bhka))
    return python, bhka


def test_one_command_install_keeps_existing_managed_login(tmp_path: Path, monkeypatch) -> None:
    python, bhka = prepare_project(tmp_path, monkeypatch)
    managed = tmp_path / ".auth" / "bilibili.cookies.txt"
    managed.parent.mkdir()
    managed.write_text("local credential placeholder", encoding="utf-8")
    (tmp_path / ".env").write_text(
        f"BILIBILI_COOKIES_FILE={managed}\n",
        encoding="utf-8",
    )
    commands: list[list[str]] = []
    monkeypatch.setattr(installer, "run", lambda command: commands.append(command) or 0)

    assert installer.install(tmp_path) == 0

    assert len(commands) == 1
    assert commands[0][0] == str(python)
    assert all(str(bhka) not in command for command in commands)


def test_one_command_install_delegates_first_login_to_portable_installer(
    tmp_path: Path,
    monkeypatch,
) -> None:
    prepare_project(tmp_path, monkeypatch)
    commands: list[list[str]] = []
    monkeypatch.setattr(installer, "run", lambda command: commands.append(command) or 0)

    assert installer.install(tmp_path) == 0

    assert commands[0][1].endswith("install.py")
    assert commands[0][2:5] == ["--agent", "codex", "--force"]
    assert "--no-login" not in commands[0]


def test_one_command_install_can_skip_login_for_ci(tmp_path: Path, monkeypatch) -> None:
    prepare_project(tmp_path, monkeypatch)
    commands: list[list[str]] = []
    monkeypatch.setattr(installer, "run", lambda command: commands.append(command) or 0)

    assert installer.install(tmp_path, login=False) == 0

    assert commands[0][-1] == "--no-login"
