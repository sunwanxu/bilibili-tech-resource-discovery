from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import yaml

SCRIPT = (
    Path(__file__).parents[1]
    / "skills"
    / "bilibili-tech-resource-discovery"
    / "scripts"
    / "onboard.py"
)
SPEC = importlib.util.spec_from_file_location("skill_onboard", SCRIPT)
assert SPEC and SPEC.loader
onboard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(onboard)

INSTALL_SCRIPT = SCRIPT.with_name("install_skill.py")
INSTALL_SPEC = importlib.util.spec_from_file_location("skill_installer", INSTALL_SCRIPT)
assert INSTALL_SPEC and INSTALL_SPEC.loader
installer = importlib.util.module_from_spec(INSTALL_SPEC)
INSTALL_SPEC.loader.exec_module(installer)

PORTABLE_SCRIPT = SCRIPT.with_name("install.py")
PORTABLE_SPEC = importlib.util.spec_from_file_location("portable_skill_installer", PORTABLE_SCRIPT)
assert PORTABLE_SPEC and PORTABLE_SPEC.loader
portable = importlib.util.module_from_spec(PORTABLE_SPEC)
PORTABLE_SPEC.loader.exec_module(portable)


def test_update_env_preserves_unrelated_secrets_without_printing(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "DEEPSEEK_API_KEY=keep-this-secret\n"
        "BILIBILI_COOKIES_FILE=old.txt\n"
        "BILIBILI_COOKIES_FROM_BROWSER=\n",
        encoding="utf-8",
    )

    onboard.update_env(
        env_path,
        {"BILIBILI_COOKIES_FILE": "", "BILIBILI_COOKIES_FROM_BROWSER": "edge"},
    )

    values = onboard.parse_env(env_path)
    assert values["DEEPSEEK_API_KEY"] == "keep-this-secret"
    assert values["BILIBILI_COOKIES_FILE"] == ""
    assert values["BILIBILI_COOKIES_FROM_BROWSER"] == "edge"


def test_cookie_check_accepts_only_bilibili_domain_rows(tmp_path: Path) -> None:
    cookie_path = tmp_path / "cookies.txt"
    cookie_path.write_text(
        "# Netscape HTTP Cookie File\n"
        ".example.com\tTRUE\t/\tFALSE\t0\tsession\tsecret\n",
        encoding="utf-8",
    )
    assert not onboard.cookie_file_has_bilibili_rows(cookie_path)

    cookie_path.write_text(
        "# Netscape HTTP Cookie File\n"
        "#HttpOnly_.bilibili.com\tTRUE\t/\tTRUE\t0\tSESSDATA\tsecret\n",
        encoding="utf-8",
    )
    assert onboard.cookie_file_has_bilibili_rows(cookie_path)


def test_configure_public_clears_both_auth_modes(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "BILIBILI_COOKIES_FILE=cookies.txt\n"
        "BILIBILI_COOKIES_FROM_BROWSER=edge\n",
        encoding="utf-8",
    )

    assert onboard.configure(tmp_path, None, None, True) == 0

    values = onboard.parse_env(tmp_path / ".env")
    assert values["BILIBILI_COOKIES_FILE"] == ""
    assert values["BILIBILI_COOKIES_FROM_BROWSER"] == ""


def test_status_does_not_claim_login_before_verification(tmp_path: Path, monkeypatch, capsys) -> None:
    cookie_path = tmp_path / "cookies.txt"
    cookie_path.write_text(
        "# Netscape HTTP Cookie File\n"
        ".bilibili.com\tTRUE\t/\tTRUE\t0\tSESSDATA\tsecret\n",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        f"BILIBILI_COOKIES_FILE={cookie_path}\n",
        encoding="utf-8",
    )
    python = tmp_path / "python"
    bhka = tmp_path / "bhka"
    python.touch()
    bhka.touch()
    monkeypatch.setattr(onboard, "venv_paths", lambda root: (python, bhka))

    assert onboard.status(tmp_path) == 0

    output = capsys.readouterr().out
    assert "[VERIFY-NEEDED]" in output
    assert "[READY]" not in output
    assert "secret" not in output


def test_status_identifies_project_managed_login(tmp_path: Path, monkeypatch, capsys) -> None:
    cookie_path = tmp_path / ".auth" / "bilibili.cookies.txt"
    cookie_path.parent.mkdir()
    cookie_path.write_text(
        "# Netscape HTTP Cookie File\n"
        ".bilibili.com\tTRUE\t/\tTRUE\t0\tSESSDATA\tsecret\n",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        f"BILIBILI_COOKIES_FILE={cookie_path}\n",
        encoding="utf-8",
    )
    python = tmp_path / "python"
    bhka = tmp_path / "bhka"
    python.touch()
    bhka.touch()
    monkeypatch.setattr(onboard, "venv_paths", lambda root: (python, bhka))

    assert onboard.status(tmp_path) == 0

    output = capsys.readouterr().out
    assert "Managed login configuration exists" in output
    assert "Project-managed .auth session" in output
    assert "secret" not in output


def test_installer_excludes_python_cache_and_writes_project_pointer(tmp_path: Path) -> None:
    project = tmp_path / "project"
    skill = project / "skills" / installer.SKILL_NAME
    (project / "pyproject.toml").parent.mkdir(parents=True)
    (project / "pyproject.toml").write_text(
        '[project]\nname = "bilibili-hidden-knowledge-agent"\n',
        encoding="utf-8",
    )
    for relative in installer.REQUIRED_FILES:
        path = skill / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder", encoding="utf-8")
    cache = skill / "scripts" / "__pycache__" / "cached.pyc"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b"cache")

    target, backup = installer.install_skill(project, tmp_path / "installed", force=False)

    assert backup is None
    assert (target / ".project-root").read_text(encoding="utf-8") == str(project.resolve())
    assert not (target / "scripts" / "__pycache__").exists()


def test_portable_installer_places_complete_skill_in_opencode_global_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(portable, "install_runtime", lambda target, login: None)

    installed = portable.install(
        "opencode",
        force=False,
        login=False,
        home=tmp_path,
    )

    target = tmp_path / ".config" / "opencode" / "skills" / portable.SKILL_NAME
    assert installed == [target]
    assert (target / "SKILL.md").is_file()
    assert (target / "runtime" / "pyproject.toml").is_file()
    assert (target / "runtime" / "src" / "bhka" / "cli.py").is_file()


def test_portable_update_preserves_managed_login_state(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(portable, "install_runtime", lambda target, login: None)
    target = portable.install("opencode", False, False, home=tmp_path)[0]
    cookie = target / "runtime" / ".auth" / "bilibili.cookies.txt"
    cookie.parent.mkdir()
    cookie.write_text("local credential placeholder", encoding="utf-8")
    venv_marker = target / "runtime" / ".venv" / "installed.txt"
    venv_marker.parent.mkdir()
    venv_marker.write_text("preserve runtime", encoding="utf-8")
    (target / "runtime" / ".env").write_text(
        (
            f"BILIBILI_COOKIES_FILE={cookie}\n"
            "BILIBILI_RETRIES=2\n"
            "BILIBILI_RATE_LIMIT_SECONDS=1.0\n"
            "FIRECRAWL_SEARCH_LIMIT=5\n"
        ),
        encoding="utf-8",
    )

    portable.install("opencode", True, False, home=tmp_path)

    assert cookie.read_text(encoding="utf-8") == "local credential placeholder"
    env = (target / "runtime" / ".env").read_text(encoding="utf-8")
    assert str(cookie.resolve()) in env
    assert "BILIBILI_RETRIES=1" in env
    assert "BILIBILI_RATE_LIMIT_SECONDS=2.5" in env
    assert "FIRECRAWL_SEARCH_LIMIT=8" in env
    assert venv_marker.read_text(encoding="utf-8") == "preserve runtime"


def test_portable_update_falls_back_when_active_skill_directory_is_locked(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(portable, "install_runtime", lambda target, login: None)
    target = portable.install("opencode", False, False, home=tmp_path)[0]
    marker = target / "local-marker.txt"
    marker.write_text("old installation", encoding="utf-8")
    real_replace = portable.os.replace

    def replace_with_active_directory_lock(source, destination):
        if Path(source) == target:
            raise PermissionError("active Skill is in use")
        return real_replace(source, destination)

    monkeypatch.setattr(portable.os, "replace", replace_with_active_directory_lock)

    portable.install("opencode", True, False, home=tmp_path)

    assert (target / "SKILL.md").is_file()
    backups = list((tmp_path / ".config" / "opencode" / "skill-backups").glob("*.backup-*"))
    assert len(backups) == 1
    assert (backups[0] / marker.name).read_text(encoding="utf-8") == "old installation"


def test_portable_install_can_migrate_state_from_legacy_project(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(portable, "install_runtime", lambda target, login: None)
    legacy = tmp_path / "legacy"
    legacy_cookie = legacy / ".auth" / "bilibili.cookies.txt"
    legacy_cookie.parent.mkdir(parents=True)
    legacy_cookie.write_text("local credential placeholder", encoding="utf-8")
    (legacy / ".env").write_text(
        f"BILIBILI_COOKIES_FILE={legacy_cookie}\n",
        encoding="utf-8",
    )

    target = portable.install(
        "opencode",
        force=False,
        login=False,
        home=tmp_path,
        state_from=legacy,
    )[0]

    migrated = target / "runtime" / ".auth" / "bilibili.cookies.txt"
    assert migrated.read_text(encoding="utf-8") == "local credential placeholder"
    assert str(migrated.resolve()) in (target / "runtime" / ".env").read_text(encoding="utf-8")


def test_empty_installed_runtime_does_not_hide_legacy_login(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(portable, "install_runtime", lambda target, login: None)
    target = portable.install("opencode", False, False, home=tmp_path)[0]
    legacy = tmp_path / "legacy"
    legacy_cookie = legacy / ".auth" / "bilibili.cookies.txt"
    legacy_cookie.parent.mkdir(parents=True)
    legacy_cookie.write_text("local credential placeholder", encoding="utf-8")
    (legacy / ".env").write_text(
        f"BILIBILI_COOKIES_FILE={legacy_cookie}\n",
        encoding="utf-8",
    )

    portable.install(
        "opencode",
        force=True,
        login=False,
        home=tmp_path,
        state_from=legacy,
    )

    migrated = target / "runtime" / ".auth" / "bilibili.cookies.txt"
    assert migrated.read_text(encoding="utf-8") == "local credential placeholder"


def test_bundled_runtime_matches_primary_source_tree() -> None:
    project = Path(__file__).parents[1]
    bundled = project / "skills" / portable.SKILL_NAME / "runtime" / "src" / "bhka"
    source = project / "src" / "bhka"

    assert {
        path.relative_to(bundled): path.read_bytes() for path in bundled.rglob("*.py")
    } == {
        path.relative_to(source): path.read_bytes() for path in source.rglob("*.py")
    }


def test_skill_ui_metadata_is_valid_utf8_and_user_facing() -> None:
    skill = Path(__file__).parents[1] / "skills" / portable.SKILL_NAME
    metadata = yaml.safe_load((skill / "agents" / "openai.yaml").read_text(encoding="utf-8"))
    interface = metadata["interface"]

    assert interface["display_name"] == "B站技术资源发现"
    assert 25 <= len(interface["short_description"]) <= 64
    assert f"${portable.SKILL_NAME}" in interface["default_prompt"]


def test_portable_installer_verifies_the_exact_bundled_runtime_version(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    target = tmp_path / "installed-skill"
    runtime = target / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "pyproject.toml").write_text(
        '[project]\nname = "bilibili-hidden-knowledge-agent"\nversion = "0.4.0"\n',
        encoding="utf-8",
    )
    python = runtime / "python"
    bhka = runtime / "bhka"
    python.touch()
    bhka.touch()
    bhka_v1 = runtime / "bhka-v1"
    bhka_v1.touch()
    monkeypatch.setattr(portable, "runtime_paths", lambda value: (python, bhka, bhka_v1))
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command == [str(bhka), "--version"]:
            return SimpleNamespace(returncode=0, stdout="bhka 0.4.0\n")
        if command == [str(bhka_v1), "--help"]:
            return SimpleNamespace(returncode=0, stdout="usage: bhka-v1\n")
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(portable.subprocess, "run", fake_run)
    monkeypatch.setattr(
        portable,
        "_pip_install",
        lambda python, runtime: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    portable.install_runtime(target, login=False)

    assert [str(bhka), "--version"] in calls
    assert "Runtime verified: bhka 0.4.0" in capsys.readouterr().out


def test_portable_installer_uses_v1_login_after_consent(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "installed-skill"
    runtime = target / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "pyproject.toml").write_text(
        '[project]\nname = "bilibili-hidden-knowledge-agent"\nversion = "0.4.0"\n',
        encoding="utf-8",
    )
    python = runtime / "python"
    bhka = runtime / "bhka"
    bhka_v1 = runtime / "bhka-v1"
    for path in (python, bhka, bhka_v1):
        path.touch()
    monkeypatch.setattr(portable, "runtime_paths", lambda _runtime: (python, bhka, bhka_v1))
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        if command == [str(python), "--version"]:
            return SimpleNamespace(returncode=0, stdout="Python 3.13\n", stderr="")
        if command == [str(bhka), "--version"]:
            return SimpleNamespace(returncode=0, stdout="bhka 0.4.0\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(portable.subprocess, "run", fake_run)
    monkeypatch.setattr(
        portable,
        "_pip_install",
        lambda _python, _runtime: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    portable.install_runtime(target, login=True)

    assert [str(bhka_v1), "login", "--project-root", str(runtime)] in calls


def test_portable_runtime_install_is_non_editable(tmp_path: Path, monkeypatch) -> None:
    captured: list[str] = []

    class FakeProcess:
        returncode = 0

        def poll(self):
            return 0

        def communicate(self):
            return "", ""

    def fake_popen(command, **_kwargs):
        captured.extend(command)
        return FakeProcess()

    monkeypatch.setattr(portable.subprocess, "Popen", fake_popen)

    result = portable._pip_install(tmp_path / "python", tmp_path / "runtime")

    assert result.returncode == 0
    assert "-e" not in captured
    assert "--upgrade" in captured
    assert captured[-1] == str(tmp_path / "runtime")


def test_portable_installer_removes_only_stale_package_rollback_artifacts(
    tmp_path: Path,
) -> None:
    site_packages = tmp_path / "Lib" / "site-packages"
    stale = site_packages / "~ilibili_hidden_knowledge_agent-0.4.0.dist-info"
    unrelated = site_packages / "~unrelated-package"
    stale.mkdir(parents=True)
    unrelated.mkdir()

    portable._remove_stale_package_artifacts(tmp_path)

    assert not stale.exists()
    assert unrelated.exists()


def test_portable_installer_rebuilds_an_unhealthy_runtime(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "installed-skill"
    runtime = target / "runtime"
    environment = runtime / ".venv"
    environment.mkdir(parents=True)
    (runtime / "pyproject.toml").write_text(
        '[project]\nname = "bilibili-hidden-knowledge-agent"\nversion = "0.4.0"\n',
        encoding="utf-8",
    )
    python = environment / "python"
    bhka = environment / "bhka"
    python.touch()
    bhka.touch()
    bhka_v1 = environment / "bhka-v1"
    bhka_v1.touch()
    monkeypatch.setattr(portable, "runtime_paths", lambda value: (python, bhka, bhka_v1))
    rebuilt = []

    class FakeBuilder:
        def __init__(self, **_kwargs):
            pass

        def create(self, path):
            rebuilt.append(Path(path))
            Path(path).mkdir(parents=True)
            python.touch()
            bhka.touch()

    def fake_run(command, **_kwargs):
        if command == [str(python), "--version"]:
            return SimpleNamespace(returncode=1, stdout="")
        if command == [str(bhka), "--version"]:
            return SimpleNamespace(returncode=0, stdout="bhka 0.4.0\n")
        if command == [str(bhka_v1), "--help"]:
            return SimpleNamespace(returncode=0, stdout="usage: bhka-v1\n")
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(portable.venv, "EnvBuilder", FakeBuilder)
    monkeypatch.setattr(portable.subprocess, "run", fake_run)
    monkeypatch.setattr(
        portable,
        "_pip_install",
        lambda python, runtime: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    portable.install_runtime(target, login=False)

    assert rebuilt == [environment]


def test_portable_update_switches_environment_when_old_launcher_is_locked(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = tmp_path / "installed-skill"
    runtime = target / "runtime"
    environment = runtime / ".venv"
    scripts = environment / ("Scripts" if portable.os.name == "nt" else "bin")
    scripts.mkdir(parents=True)
    (runtime / "pyproject.toml").write_text(
        '[project]\nname = "bilibili-hidden-knowledge-agent"\nversion = "0.4.0"\n',
        encoding="utf-8",
    )
    old_python = scripts / ("python.exe" if portable.os.name == "nt" else "python")
    old_bhka = scripts / ("bhka.exe" if portable.os.name == "nt" else "bhka")
    old_python.touch()
    old_bhka.touch()
    created: list[Path] = []

    class FakeBuilder:
        def __init__(self, **_kwargs):
            pass

        def create(self, path):
            new_environment = Path(path)
            created.append(new_environment)
            new_scripts = new_environment / ("Scripts" if portable.os.name == "nt" else "bin")
            new_scripts.mkdir(parents=True)
            (new_scripts / ("python.exe" if portable.os.name == "nt" else "python")).touch()
            (new_scripts / ("bhka.exe" if portable.os.name == "nt" else "bhka")).touch()

    def fake_run(command, **_kwargs):
        if command == [str(old_python), "--version"]:
            return SimpleNamespace(returncode=0, stdout="Python 3.12\n", stderr="")
        if command[-1] == "--version":
            return SimpleNamespace(returncode=0, stdout="bhka 0.4.0\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    install_attempts = 0

    def fake_pip_install(python, runtime):
        nonlocal install_attempts
        install_attempts += 1
        if install_attempts == 1:
            return SimpleNamespace(returncode=1, stdout="", stderr="launcher is locked")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(portable.venv, "EnvBuilder", FakeBuilder)
    monkeypatch.setattr(portable.subprocess, "run", fake_run)
    monkeypatch.setattr(portable, "_pip_install", fake_pip_install)

    portable.install_runtime(target, login=False)

    assert len(created) == 1
    assert created[0].name.startswith(".venv-0.4.0-")
    assert portable.runtime_environment(runtime) == created[0]
