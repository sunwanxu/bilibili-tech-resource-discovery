# Natural-language discovery workflow

The `discover` command turns a technical need into a bounded Bilibili research run:

```powershell
.\.venv\Scripts\bhka discover `
  "零基础使用嘉立创EDA画STM32最小系统板，寻找教程和开源工程" `
  --max-candidates 80 `
  --deep 8
```

The command performs these steps:

1. Expands the need into several explainable Chinese search queries.
2. Collects direct project links and public Bilibili candidates from available web indexes.
3. Keeps internal Bilibili search disabled unless an explicit bounded diagnostic enables it.
4. Deduplicates search results and rewards candidates found by multiple queries.
5. Deeply inspects a bounded number of candidates.
6. Reads metadata, descriptions, available subtitles, and one top-comment page.
7. Extracts repositories, hardware projects, cloud drives, documents, and QQ groups.
8. Keeps a strict distinction between a verified license, an unverified public repository,
   shared files with unknown terms, and a promise to open-source later.
9. Inspects supported external projects for schematic, PCB, BOM, Gerber, source code,
   documentation, license, and hardware-validation evidence.
10. Follows supported repository links found on a project page or in a README.
11. Writes JSON evidence and a Markdown report.

Before expanding queries, configured authentication is checked once through Bilibili's account-status
endpoint. Browser database locks, Windows DPAPI failures, missing profiles, and HTTP 412 responses
stop further Bilibili requests. The run records `success`, `partial_success`, or `failed`; a fully
failed discovery returns a nonzero process exit code.

Outputs are saved under:

- `data/discovery/<requirement>/<run-id>.json`: immutable machine-readable run history
- `reports/discovery/<requirement>/<run-id>.md`: immutable human-readable run history
- `latest.json` / `latest.md`: most recent non-failed run for that requirement

Writes are atomic. Failed runs remain available for diagnosis but never replace `latest`.

Configure login without an extension or an additional browser:

```powershell
.\.venv\Scripts\bhka login --project-root .
```

This opens a visible, isolated Microsoft Edge context. After the user completes normal Bilibili
login, the command saves only Bilibili-domain cookies in the project's Git-ignored `.auth/` folder,
restricts access, records the matching user agent, and verifies `isLogin`.

Verify an existing login without exposing identity or credentials:

```powershell
.\.venv\Scripts\bhka auth-status --json --project-root .
```

Reading a daily Edge/Chrome profile remains a fallback because Windows DPAPI/App-Bound encryption can
block third-party decryption. Managed `bhka login` avoids that path.

## Evidence boundaries

- The command does not download or watch complete videos.
- If subtitles are unavailable, the report says so explicitly.
- GitHub licenses are checked through GitHub's public API.
- GitHub file trees and READMEs are inspected without cloning the repository.
- A license displayed by a hardware-sharing platform is reported separately because the
  platform's additional terms may need review.
- Cloud-drive and community-group resources are never labeled open source without an
  independent license.
- Search and comment reads stay bounded; this is not a bulk crawler.

Use `--no-comments` for a faster metadata-only run, or lower `--deep` for a smoke test.
Internal search is off by default. Repeated requirements and BVID evidence use a seven-day local
cache. Use `--summary-json` for UTF-8 machine-readable output.
