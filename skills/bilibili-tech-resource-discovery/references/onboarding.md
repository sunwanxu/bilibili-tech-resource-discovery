# First-run onboarding and recovery

## Contents

- First-run promise
- Recommended path
- Browser login
- Cookie-file fallback
- Recovery table
- Successful handoff
- Optional public-web enhancement

## First-run promise

Keep the user moving. Perform checks yourself when tools allow it. Give one concrete action at a time,
then verify it. Do not dump a long setup guide before knowing what is missing.

State these privacy facts before authentication setup:

- The workflow reads the user's own local Bilibili session.
- Credentials remain on the user's device.
- Cookie and API-key values are excluded from logs and reports.
- The user can use public-data mode without configuring login, with reduced comment/subtitle coverage.

## Recommended path

1. Resolve the folder containing `SKILL.md`.
2. Run `python <skill>/scripts/install.py --agent <current-host>` once. Use `codex` or `opencode`
   internally; do not ask the user to choose.
3. If Edge opens, ask the user only to complete normal Bilibili login in that window.
4. Start the user's resource request after installation succeeds.

The self-contained Skill folder includes its runtime. The installer copies it to the host's global
Skill location, creates or updates the virtual environment under `<installed-skill>/runtime`,
preserves an existing managed session, and starts first-time managed login. Use `--no-login` only for
CI or offline installation checks. Do not require an external repository or a Codex-specific path.
If Windows has locked an older runtime launcher, the installer silently builds a fresh private
environment and records it in `runtime/.venv-path`; resolve `<bhka>` using the rule in `SKILL.md`.
Do not ask the user to close or restart the agent merely to complete an update.

Plain `status` performs no network request. A locally complete authentication configuration returns
exit code 0 with `VERIFY-NEEDED`; use `status --verify-auth` only when a network verification is
appropriate. Managed sessions are labeled `Project-managed .auth session`, while user-supplied
Netscape files are labeled `External Netscape cookie file`.

Treat `onboard.py`, `status`, `configure`, and individual pip commands as developer recovery tools.
Do not present them during a normal installation unless the unified installer reports a specific
failure that requires one of them.

Managed Edge login is the default path. It obtains the session through the browser's supported
automation context, writes only Bilibili-domain cookies under the installed runtime's Git-ignored
`.auth/` folder, records the matching user agent, and verifies `isLogin`. It does not decrypt the daily Edge
cookie database and does not require Firefox or a cookie extension.

## Browser login

Use `<bhka> login --project-root <installed-skill>/runtime`, where `<bhka>` is the exact bundled
executable defined in `SKILL.md`; never use a bare command from `PATH`. Keep the window visible. The user may scan a QR code or use
their normal login method. Do not fill credentials, inspect form values, take screenshots, or log
browser storage. Close the isolated context automatically after login is detected and verified.

The saved Netscape file is still a login credential. Restrict it to the current OS user, exclude it
from reports and Git, and replace it atomically on the next login. Warn against placing the companion
project in a cloud-synced or shared folder.

## Existing-browser fallback

Supported values are `brave`, `chrome`, `chromium`, `edge`, `firefox`, `opera`, `safari`, `vivaldi`,
and `whale`. A non-default profile can be written as `chrome:Profile 1`.

The browser database can be locked while the browser or a background process is running. Only ask the
user to close the selected browser after saving their work. On Windows, closing the window may leave a
background process; the status command reports this as a warning. Never terminate the user's browser
without explicit permission.

Browser-cookie reading can also fail when the AI process runs under a different operating-system user
or lacks access to the browser's encrypted cookie store. On Windows, a DPAPI/App-Bound error from
Edge or Chrome is a terminal result for that method: do not retry or terminate browser processes.
Offer Firefox, a trusted local Netscape cookie file, or public-data mode.

## Cookie-file fallback

Accept only a local Netscape-format cookie file. Do not ask the user to paste its contents. Prefer a
file containing only Bilibili domains. Verify that it contains Bilibili-domain rows, but never display
the values.

Warn the user:

- Treat the file like a password.
- Store it outside shared/cloud-synced folders when possible.
- Never commit it to Git or upload it to the AI conversation.
- Delete an all-sites export after creating a Bilibili-only copy and validating the setup.

Do not direct users to an unknown browser extension. If they cannot export safely, use public-data
mode until a trusted method is available.

## Recovery table

| Symptom | Meaning | Next action |
|---|---|---|
| Python is missing or older than 3.11 | Runtime cannot start | Help install Python 3.11+ from the official distribution, then re-run status. |
| Virtual environment missing | Dependencies are not installed | Ask permission, run `onboard.py install`, then re-run status. |
| Browser process may be running | Cookie database may be locked | Ask user to save work and fully close only that browser, then retry. |
| Browser profile not found | Wrong browser/profile name | Ask which profile contains the Bilibili login; configure `browser:profile`. |
| Managed Edge window will not open | Edge is missing or blocked by policy | Use an existing Firefox session or a trusted local Netscape cookie file. |
| Existing Edge/Chrome DPAPI or App-Bound error | Daily-profile cookie decryption is blocked | Stop retries and use `<bhka> login`; do not weaken browser security. |
| Managed login times out | Login was not completed or the window closed | Run `<bhka> login` once more and complete login within the displayed time. |
| Cookie file missing | Configured path is stale | Select the correct file or return to browser mode. |
| Cookie file has no Bilibili rows | Wrong or incomplete export | Create a Bilibili-only Netscape export locally; do not paste it. |
| HTTP 412 / risk-control response | Bilibili rate limiting or risk control | Stop direct Bilibili requests, use cached evidence or a bounded web-index fallback, and wait before deep inspection. |
| Comments unavailable | Login, permissions, or upstream limitation | Continue without comments and label the gap. |
| Subtitles unavailable | Video has no accessible subtitle track | Use description/comments/repository evidence; do not infer video speech. |
| Repository/cloud link needs login | Automated inspection is incomplete | Keep the link in a final human-review section. |

Never solve 412 errors with aggressive retries, proxies, account rotation, or bypass techniques.
Never recommend cookie-unlock plugins, disabling browser encryption, or killing browser processes.
An ordinary search-engine query restricted to `site:bilibili.com/video` is an acceptable candidate
fallback because it does not retry the blocked Bilibili endpoint. Label it as web-index evidence and
defer subtitle/comment inspection until the cooldown has passed.

Use `<bhka> analyze <BV> --summary-json` for smoke-test automation. It returns content-free counts and
structured warning/error codes. Add `--retain-raw` only when local evidence retention is necessary;
retained raw data excludes uploader and commenter identifiers.

## Successful handoff

On success, tell the user:

- the selected local authentication mode, without credential values;
- that a small Bilibili request succeeded;
- where reports will be saved;
- how to disable login by clearing both Bilibili authentication settings;
- that the next request can be phrased naturally.

## Public-web discovery and optional enhancement

Normal public-web discovery requires no account or API key. The built-in public index searches
indexed Bilibili video pages plus GitHub, Gitee, and OSHWHub projects. Firecrawl is an optional
coverage enhancement only. If configured, store `FIRECRAWL_API_KEY` in the installed runtime's local
`.env`; never echo it, pass it on the command line, copy it into the Skill package, or place it in a
report. `discover` tries Firecrawl first and falls back to the keyless index when needed. Neither
provider replaces Bilibili login, subtitle/comment retrieval, resource evaluation, or license
verification.
