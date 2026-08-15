# Windows-first onboarding and recovery

Use this reference only when installation, private Edge login, or the first request fails. Normal
users should need only one natural-language request and, if they agree, one visible login window.

## Privacy promise

- Login is optional and uses the user's own Bilibili account.
- The private Edge profile and exported Bilibili-only credential stay under the installed Skill.
- Cookie/API-key values, UID, nickname, and comment-author identity are excluded from reports.
- Public mode remains usable, with weaker subtitle/comment coverage.

## Normal installation

When an AI is installing, ask for login consent first. Then run exactly one of:

```text
python <skill>/scripts/install.py --agent codex --force --login
python <skill>/scripts/install.py --agent codex --force --no-login
python <skill>/scripts/install.py --agent opencode --force --login
python <skill>/scripts/install.py --agent opencode --force --no-login
```

When a person runs `install-windows.cmd` or `python install.py` directly, the installer asks the same
question. A noninteractive install safely skips login unless `--login` is explicit.

`install-windows.cmd` does not require preinstalled Python. When Python is absent, it installs pinned
uv 0.11.32 into `%LOCALAPPDATA%\bilibili-tech-resource-discovery\tools`, without changing the global
`PATH`, and uv downloads a private Python runtime. This follows uv's official unmanaged-install path.

The installer copies the complete Skill, builds a private non-editable Python environment, preserves
existing `.auth`, reports, data, and `.env`, and verifies both the stable and v1 commands. It does not
read a daily Edge profile, use DPAPI, require Firefox, or install a Cookie extension.

## Login

Run the exact private v1 executable:

```text
<bhka-v1> login --project-root <runtime>
```

The user completes normal login in the visible project-owned Edge window. Do not fill credentials,
inspect form values, take screenshots, or print browser storage. The resulting Netscape file is a
credential even though it contains only Bilibili-domain cookies; keep it local and Git-ignored.

The existence of a credential file proves only that configuration exists. A successful bounded video
read proves that the current session works. If login verification fails, continue public discovery and
label missing subtitle/comment evidence rather than declaring that no resources exist.

## Recovery table

| Symptom | Meaning | Safe recovery |
|---|---|---|
| Python is missing | The bootstrap must obtain its own runtime | Run `install-windows.cmd`; it uses pinned uv and a private Python automatically. |
| Private environment incomplete | An install was interrupted or files were locked | Rerun the installer with `--force`; it can switch to a fresh environment. |
| Edge window does not open | Edge is unavailable or blocked by policy | Continue public mode; do not fall back to unknown extensions. |
| Login times out | The visible login was not completed | Ask whether to open the private login window once more. |
| Credential exists but video read is unauthenticated | Session expired | Ask consent to log in again; do not paste or inspect Cookie values. |
| HTTP 412 | Bilibili-side risk control | Stop all Bilibili calls for this run, keep checkpoints, and use public/repository evidence. |
| One video URL is malformed | Bad candidate or extractor input | Skip that candidate, save completed checkpoints, and continue. |
| Subtitle unavailable | The video has no accessible track | Use description, bounded comments, repository evidence, and label the gap. |
| Repository/shared page needs login | Automated validation is incomplete | Keep it as a human-review lead; do not call it verified open source. |

Never respond to 412 with repeated retries, proxies, account rotation, CAPTCHA bypass, deletion of
local state, or disabling browser security. A local cooldown is only a client safety suggestion; the
service decides when access is restored.

## Successful handoff

Tell the user only:

- installation succeeded;
- whether login or public mode is active, without account identity;
- reports will be stored locally under `<runtime>/reports/v1`;
- they can now describe a learning or resource need naturally.
