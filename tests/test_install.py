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
    _, bhka = prepare_project(tmp_path, monkeypatch)
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
    assert commands[0][0] == installer.sys.executable
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
    assert commands[0][2:5] == ["--agent", "auto", "--force"]
    assert "--no-login" not in commands[0]


def test_one_command_install_can_skip_login_for_ci(tmp_path: Path, monkeypatch) -> None:
    prepare_project(tmp_path, monkeypatch)
    commands: list[list[str]] = []
    monkeypatch.setattr(installer, "run", lambda command: commands.append(command) or 0)

    assert installer.install(tmp_path, login=False) == 0

    assert commands[0][-1] == "--no-login"


def test_one_command_install_accepts_known_host_and_isolated_home(
    tmp_path: Path,
    monkeypatch,
) -> None:
    prepare_project(tmp_path, monkeypatch)
    commands: list[list[str]] = []
    monkeypatch.setattr(installer, "run", lambda command: commands.append(command) or 0)
    isolated_home = tmp_path / "new-user"

    assert installer.install(
        tmp_path,
        login=False,
        agent="opencode",
        home=isolated_home,
    ) == 0

    assert commands[0][2:5] == ["--agent", "opencode", "--force"]
    assert commands[0][-3:] == ["--home", str(isolated_home), "--no-login"]
    assert "--state-from" not in commands[0]


def test_windows_launcher_bootstraps_pinned_uv_without_global_path_changes() -> None:
    launcher = (SCRIPT.parent / "install-windows.cmd").read_text(encoding="utf-8")

    assert "uv-0.11.32" in launcher
    assert "https://astral.sh/uv/0.11.32/install.ps1" in launcher
    assert "UV_UNMANAGED_INSTALL" in launcher
    assert "UV_NO_MODIFY_PATH" in launcher
    assert '"%BHKA_UV_EXE%" run --no-project --python 3.13' in launcher
