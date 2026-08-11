#!/usr/bin/env python3
"""Local first-run helper. It never prints cookie or API-key values."""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import venv
from pathlib import Path

PROJECT_NAME = "bilibili-hidden-knowledge-agent"
SUPPORTED_BROWSERS = {
    "brave",
    "chrome",
    "chromium",
    "edge",
    "firefox",
    "opera",
    "safari",
    "vivaldi",
    "whale",
}
SENSITIVE_KEYS = {
    "OPENAI_API_KEY",
    "DEEPSEEK_API_KEY",
}


def is_project_root(path: Path) -> bool:
    pyproject = path / "pyproject.toml"
    if not pyproject.is_file():
        return False
    try:
        content = pyproject.read_text(encoding="utf-8")
    except OSError:
        return False
    return f'name = "{PROJECT_NAME}"' in content


def ancestors(start: Path):
    current = start.resolve()
    yield current
    yield from current.parents


def resolve_project_root(explicit: str | None) -> Path | None:
    starts: list[Path] = []
    if explicit:
        starts.append(Path(explicit).expanduser())
    env_root = os.getenv("BHKA_PROJECT_ROOT", "").strip()
    if env_root:
        starts.append(Path(env_root).expanduser())
    bundled_runtime = Path(__file__).resolve().parents[1] / "runtime"
    if is_project_root(bundled_runtime):
        starts.append(bundled_runtime)
    pointer = Path(__file__).resolve().parents[1] / ".project-root"
    if pointer.is_file():
        stored_root = pointer.read_text(encoding="utf-8").strip()
        if stored_root:
            starts.append(Path(stored_root).expanduser())
    starts.extend([Path.cwd(), Path(__file__).resolve()])
    seen: set[Path] = set()
    for start in starts:
        for candidate in ancestors(start if start.is_dir() else start.parent):
            if candidate in seen:
                continue
            seen.add(candidate)
            if is_project_root(candidate):
                return candidate
    return None


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def update_env(path: Path, updates: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8-sig").splitlines() if path.is_file() else []
    remaining = dict(updates)
    output: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in remaining:
                output.append(f"{key}={remaining.pop(key)}")
                continue
        output.append(line)
    if remaining and output and output[-1] != "":
        output.append("")
    output.extend(f"{key}={value}" for key, value in remaining.items())
    path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


def browser_name(spec: str) -> str:
    return spec.partition(":")[0].strip().lower()


def browser_process_running(browser: str) -> bool:
    aliases = {
        "brave": ("brave",),
        "chrome": ("chrome",),
        "chromium": ("chromium",),
        "edge": ("msedge", "microsoft edge"),
        "firefox": ("firefox",),
        "opera": ("opera",),
        "safari": ("safari",),
        "vivaldi": ("vivaldi",),
        "whale": ("whale",),
    }
    try:
        if os.name == "nt":
            result = subprocess.run(
                ["tasklist", "/NH", "/FO", "CSV"],
                capture_output=True,
                check=False,
                text=True,
                timeout=5,
            )
        else:
            result = subprocess.run(
                ["ps", "-e", "-o", "comm="],
                capture_output=True,
                check=False,
                text=True,
                timeout=5,
            )
    except (OSError, subprocess.TimeoutExpired):
        return False
    process_text = result.stdout.lower()
    return any(alias in process_text for alias in aliases.get(browser, (browser,)))


def cookie_file_has_bilibili_rows(path: Path) -> bool:
    try:
        for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            if line.startswith("#HttpOnly_"):
                line = line.removeprefix("#HttpOnly_")
            if line.startswith("#") or not line.strip():
                continue
            domain = line.split("\t", 1)[0].lower()
            if domain == "bilibili.com" or domain.endswith(".bilibili.com"):
                return True
    except OSError:
        return False
    return False


def venv_paths(root: Path) -> tuple[Path, Path]:
    if os.name == "nt":
        return root / ".venv" / "Scripts" / "python.exe", root / ".venv" / "Scripts" / "bhka.exe"
    return root / ".venv" / "bin" / "python", root / ".venv" / "bin" / "bhka"


def verify_auth(bhka: Path, root: Path) -> tuple[str, str | None]:
    try:
        result = subprocess.run(
            [str(bhka), "auth-status", "--json", "--project-root", str(root)],
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "verification_failed", "runtime"
    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return "verification_failed", "runtime"
    return payload.get("status", "verification_failed"), payload.get("failure_category")


def status(root: Path, verify: bool = False) -> int:
    print("Bilibili resource discovery preflight")
    print(f"[OK] Companion project found: {root}")
    version_ok = sys.version_info >= (3, 11)
    print(f"[{'OK' if version_ok else 'ACTION'}] Python: {platform.python_version()} (3.11+ required)")

    venv_python, bhka = venv_paths(root)
    runtime_ok = venv_python.is_file() and bhka.is_file()
    print(f"[{'OK' if runtime_ok else 'ACTION'}] Local runtime: {'ready' if runtime_ok else 'not installed'}")

    env_path = root / ".env"
    env = parse_env(env_path)
    browser = env.get("BILIBILI_COOKIES_FROM_BROWSER", "").strip()
    cookie_file = env.get("BILIBILI_COOKIES_FILE", "").strip()
    auth_configured = False
    auth_problem = False
    if browser and cookie_file:
        print("[ACTION] Authentication conflict: configure a browser or cookie file, not both.")
        auth_problem = True
    elif browser:
        name = browser_name(browser)
        if name not in SUPPORTED_BROWSERS:
            print(f"[ACTION] Unsupported browser setting: {name}")
            auth_problem = True
        else:
            auth_configured = True
            print(f"[CONFIGURED] Local authentication mode: browser ({name}); login not yet verified.")
            if os.name == "nt" and name != "firefox":
                print(
                    "[WARN] Chromium-based browser cookies may not be decryptable on Windows; "
                    "Firefox is the recommended browser-login path."
                )
            if browser_process_running(name):
                print(f"[WARN] {name} appears to be running; its cookie database may be locked.")
    elif cookie_file:
        cookie_path = Path(cookie_file).expanduser()
        if not cookie_path.is_absolute():
            cookie_path = root / cookie_path
        if not cookie_path.is_file():
            print("[ACTION] Configured cookie file does not exist.")
            auth_problem = True
        elif not cookie_file_has_bilibili_rows(cookie_path):
            print("[ACTION] Cookie file has no readable Bilibili-domain rows.")
            auth_problem = True
        else:
            auth_configured = True
            managed_cookie = root / ".auth" / "bilibili.cookies.txt"
            try:
                managed = cookie_path.resolve() == managed_cookie.resolve()
            except OSError:
                managed = False
            if managed:
                print("[CONFIGURED] Managed login configuration exists.")
                print("[SOURCE] Project-managed .auth session; login not yet verified.")
            else:
                print("[CONFIGURED] External Netscape cookie file; login not yet verified.")
    else:
        print("[INFO] No login configured. Public-data mode can still be used.")

    configured_keys = sorted(key for key in SENSITIVE_KEYS if env.get(key))
    if configured_keys:
        print(f"[OK] Optional AI provider configured: {', '.join(key.removesuffix('_API_KEY') for key in configured_keys)}")
    else:
        print("[INFO] No external AI key configured; discovery still works and the host AI can summarize.")

    if version_ok and runtime_ok and auth_configured and not auth_problem:
        if not verify:
            print("[VERIFY-NEEDED] Configuration exists. Re-run status with --verify-auth.")
            return 0
        auth_status, category = verify_auth(bhka, root)
        if auth_status == "valid":
            print("[LOGIN-VALID] isLogin: true")
            print("[READY] Authenticated Bilibili access is verified.")
            return 0
        if auth_status == "invalid":
            print("[LOGIN-INVALID] isLogin: false")
            print("[PUBLIC-ONLY] The configured session is expired or logged out.")
            return 2
        print(f"[AUTH-UNAVAILABLE] Login verification failed ({category or 'unknown'}).")
        if category == "authentication" and browser and os.name == "nt":
            print("[RECOVERY] Log in to Bilibili with Firefox, or use a local Netscape cookie file.")
        return 2
    if auth_problem:
        print("[SETUP-NEEDED] Fix the authentication ACTION item, then run status again.")
        return 2
    if version_ok and runtime_ok:
        print("[READY-PUBLIC] Public-data mode is ready; login can be configured for better coverage.")
        return 0
    print("[SETUP-NEEDED] Complete the ACTION items above, then run status again.")
    return 2


def install(root: Path) -> int:
    if sys.version_info < (3, 11):  # noqa: UP036 - this script diagnoses older host Pythons
        print("Python 3.11 or newer is required before installation.")
        return 2
    venv_dir = root / ".venv"
    if not venv_dir.exists():
        print("Creating a local virtual environment...")
        venv.EnvBuilder(with_pip=True).create(venv_dir)
    venv_python, _ = venv_paths(root)
    print("Installing the companion runtime into the local virtual environment...")
    result = subprocess.run(
        [str(venv_python), "-m", "pip", "install", "-e", str(root)],
        check=False,
    )
    if result.returncode:
        print("Installation did not complete. Keep the error above and ask the AI to diagnose it.")
        return result.returncode
    print("Installation completed. Run the status command next.")
    return 0


def configure(root: Path, browser: str | None, cookie_file: str | None, public: bool) -> int:
    env_path = root / ".env"
    if not env_path.exists() and (root / ".env.example").is_file():
        env_path.write_text((root / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
    if browser:
        name = browser_name(browser)
        if name not in SUPPORTED_BROWSERS:
            print("Unsupported browser. Choose: " + ", ".join(sorted(SUPPORTED_BROWSERS)))
            return 2
        if ":" in browser and not browser.partition(":")[2].strip():
            print("Browser profile cannot be empty after ':'.")
            return 2
        update_env(
            env_path,
            {"BILIBILI_COOKIES_FROM_BROWSER": browser, "BILIBILI_COOKIES_FILE": ""},
        )
        print(f"Configured local browser authentication for {name}. No Cookie value was copied.")
        if os.name == "nt" and name != "firefox":
            print(
                "Windows may block Chromium cookie decryption. Firefox is recommended if "
                "verification fails."
            )
    elif cookie_file:
        path = Path(cookie_file).expanduser().resolve()
        if not path.is_file():
            print("Cookie file does not exist. No configuration was changed.")
            return 2
        if not cookie_file_has_bilibili_rows(path):
            print("Cookie file has no readable Bilibili-domain rows. No configuration was changed.")
            return 2
        update_env(
            env_path,
            {"BILIBILI_COOKIES_FILE": str(path), "BILIBILI_COOKIES_FROM_BROWSER": ""},
        )
        print("Configured a local Bilibili cookie file. Its contents were not displayed or copied.")
    elif public:
        update_env(
            env_path,
            {"BILIBILI_COOKIES_FILE": "", "BILIBILI_COOKIES_FROM_BROWSER": ""},
        )
        print("Configured public-data mode. Comments or subtitles may have reduced coverage.")
    else:
        raise AssertionError("one configuration mode is required")
    print("Run status next, then verify with a small Bilibili request.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "install"):
        command = subparsers.add_parser(name)
        command.add_argument("--project-root")
        if name == "status":
            command.add_argument(
                "--verify-auth",
                action="store_true",
                help="make one safe request and report only whether the session is logged in",
            )
    configure_parser = subparsers.add_parser("configure")
    configure_parser.add_argument("--project-root")
    mode = configure_parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--browser", help="browser or browser:profile, for example edge")
    mode.add_argument("--cookie-file", help="local Netscape-format cookie file")
    mode.add_argument("--public", action="store_true", help="do not use authenticated data")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = resolve_project_root(args.project_root)
    if root is None:
        print(
            "Companion project not found. Open or clone bilibili-hidden-knowledge-agent, "
            "then pass its path with --project-root."
        )
        return 2
    if args.command == "status":
        return status(root, args.verify_auth)
    if args.command == "install":
        return install(root)
    return configure(root, args.browser, args.cookie_file, args.public)


if __name__ == "__main__":
    raise SystemExit(main())
