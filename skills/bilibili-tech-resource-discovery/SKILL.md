---
name: bilibili-tech-resource-discovery
description: Search Bilibili for high-quality technical learning videos or usable open-source projects from a natural-language need. Use descriptions, subtitles, bounded comments, repositories, PCB artifacts, download links, and license evidence instead of judging by titles alone. Use for tutorials, learning paths, source code, PCB projects, competition solutions, build references, design alternatives, or Bilibili login/setup for this workflow.
---

# Bilibili Technical Resource Discovery v1

The user speaks naturally. Do not ask them to write search keywords, locate video URLs, choose CLI
flags, install Firefox, export cookies, or paste credentials. Handle setup and search details yourself.

## Find the portable runtime

Treat the directory containing this file as `<skill>` and `<skill>/runtime` as `<runtime>`. Resolve
the active private environment from `<runtime>/.venv-path` when that file exists; otherwise use
`<runtime>/.venv`.

- Windows v1 command: `<environment>/Scripts/bhka-v1.exe`
- Windows login command: `<environment>/Scripts/bhka-v1.exe login`
- macOS/Linux equivalents live under `<environment>/bin/`

Never use a bare command from `PATH`. The v1 engine is isolated from the stable v0.8 command while
acceptance testing is in progress.

## First use

If the portable runtime is missing, run:

```text
python <skill>/scripts/install.py --agent <current-host> --force --no-login
```

On Windows, if Python is not already available, run the repository's `install-windows.cmd` instead.
It installs a pinned uv executable under the user's local application-data folder, lets uv obtain a
private Python runtime, and then runs the same installer. It does not modify the system Python or
global `PATH`.

Do not open a login window until the user agrees. Explain the choice simply:

- Login: better access to subtitles and comments; a private Edge window and credential file remain
  on this device.
- No login: public search still works, but some subtitles, comments, and videos may be unavailable.

After agreement, use `--login` during installation or run:

```text
<bhka-v1> login --project-root <runtime>
```

Only ask the user to finish normal Bilibili login in the visible, project-owned Edge window. Never
inspect or print Cookie values. Read [references/onboarding.md](references/onboarding.md) only when
installation or login fails.

## Understand the request before searching

Build a small internal profile containing the goal, current level, hard constraints, result type,
resource volume, and verification scope. Ask one short question at a time. Use adaptive depth rather
than a fixed question limit: stop when another answer would not materially change the queries,
ranking, evidence collection, or verification. Never present a long questionnaire all at once, and
never repeat information the user already supplied.

Use the problem to decide what remains worth asking:

- A clear, simple request may need only one or two confirmations.
- A learning request may need the mode, current level, desired endpoint, available time, preferred
  language, or software version—but ask only items that change the learning path.
- A resource request may need the exact artifact type, fixed hardware/software, acceptable platform,
  approximate quantity, inspiration versus direct reuse, verification depth, and license/commercial
  constraints.
- A complex build or competition problem may justify four to seven progressive questions about the
  current design, known constraints, failed approaches, required deliverables, and desired alternative
  routes. Skip every item already clear from the conversation.

Keep a silent checklist of goal, mode, level, constraints, expected deliverable, quantity, and
verification. Ask the highest-impact unresolved item next. If the user says “直接搜索”“先搜再说” or
otherwise wants to stop answering, stop immediately and apply the stable defaults below.

For each new need, first ask unless the user already selected a named mode or explicitly requested no
questions: “这次更想要哪种结果：1）学习路线和教程，2）搜索可用的开源资料或方案，3）两者
都要？” Do not silently infer the result type merely from words such as “学习”“PCB” or “开源”.

- `learning`: understanding, tutorials, courses, and a viewing path.
- `resource`: reusable code, PCB/EDA files, models, data, projects, or design inspiration.
- `both`: return a learning path and a separately ranked resource collection.

If the user chooses `resource` or `both`, next ask: “希望精选少量高价值资料，还是进入大量探索
模式寻找灵感？也可以直接告诉我大约需要多少个，例如 10 个或 30 个。” Map a small curated
answer to `--resource-style curated`; map inspiration, broad exploration, or roughly 20+ items to
`--resource-style inspiration`. Pass an explicit approximate count with `--resource-count`. Large
mode expands public-web and candidate coverage; it does not imply that every lead is deeply checked.

For `resource` or `both`, ask when not already answered: “是否对找到的资源进行检查？核心检查
会确认最重要链接的访问、文件和许可证；全部检查更慢；不检查则只作为灵感线索。” Map the
answer to `none`, `core`, or `all`. In inspiration mode, `core` checks only the strongest subset and
retains the rest as clearly unverified leads. Never silently choose `none` for a usable/open-source
request.

Ask additional questions only when the goal, level, deliverable, or fixed hardware/software constraint
is genuinely unclear and would change the result. If the user asks to search immediately, use stable defaults: `learning` for an explicitly
learning-only request, otherwise `resource`; curated standard breadth, core verification, minimal
retention, and no optional API key.

## Plan broad but bounded searches

Generate one precise query first, then up to three progressive variants. Preserve years, A-Z problem
letters, model numbers, acronyms, quoted phrases, platform names, and the user's actual topic. Avoid
duplicated words and fixed task-specific vocabularies.

Use the host's ordinary public web search when available to discover indexed Bilibili video pages and
direct GitHub, Gitee, OSHWHub/JLC, GitCode, Codeberg, documentation, and shared-file links. Feed precise
queries to the v1 engine with repeated `--query`, discovered Bilibili pages with repeated
`--candidate-url`, and direct project links with repeated `--resource-url`. Do not make the user
collect URLs. Numeric AV ids, `av...`, BV ids, and full Bilibili video URLs are accepted consistently.

Run the engine with one natural-language request:

```text
<bhka-v1> discover "<user request>" --mode <learning-resource-or-both> --breadth standard --resource-style <curated-or-inspiration> --resource-count <approximate-count> --verification core --query "<precise query>" --project-root <runtime>
```

When Bilibili search is disabled or a run-wide circuit is already open, use
`--no-bilibili-search` with host-discovered `--candidate-url` and `--resource-url` inputs. The engine
must retain and optionally verify those resources without opening Edge or consuming any Bilibili
request budget.

The runtime searches the normal Bilibili web page in a visible, project-owned Edge context. It does
not call an undocumented bulk-search API. Candidate discovery is broad; description, subtitle, and
comment reading is deliberately limited to the best candidates. One malformed or unavailable video
must not discard completed work.

Use `--deep-read 0` for a discovery-only smoke test. Standard defaults inspect three candidates;
deep breadth inspects six. Do not repeatedly rerun the same request: use the SQLite checkpoints and
`reports/v1/latest.json`.

## Rank without deleting the search space

Keep the complete deduplicated candidate pool in the report and separately select the strongest
items. Use explainable soft scores and diversity; do not hard-code domain-specific allowlists or
blacklists. Never reject every candidate and then restore the same list.

For learning, prioritize topic fit, level fit, coherent progression, practical demonstration, and
course completeness. For resources, prioritize evidence of accessible project links, required
artifacts, reproducibility, documentation, and verified license scope. Popularity alone is weak
evidence.

## Read evidence and mine resources

For each bounded deep read, distinguish evidence from:

- metadata and description;
- subtitle track and language;
- at most 20 top-level comments for resource mode;
- external repository or project pages;
- human-only/login-required pages.

Do not say that the AI watched the full video. Say which evidence channels were actually read.

Extract full and bare repository URLs from descriptions, subtitles, and bounded comments. Merge the
same resource across videos while preserving every origin. A component repository's license applies
only to that component; it cannot prove that a complete competition package or hardware design is
open source.

Read [references/evidence-standard.md](references/evidence-standard.md) before making open-source or
artifact-completeness claims. Default to core verification; use full verification only after the user
chooses the slower option.

## Handle rate limits and failures

Use one run-wide Bilibili request budget. If HTTP 412 appears, stop every remaining direct Bilibili
request in that run, including metadata, subtitle, and comment reads. Keep candidates and checkpoints
already obtained, continue only public-web or repository work, and explain that 412 is Bilibili-side
risk control—not a Skill prohibition or proof that login failed. Never use aggressive retries,
proxies, account rotation, CAPTCHA bypass, or deletion of local cooldown files as a workaround.

The report writer atomically saves each run under `reports/v1/runs/<run-id>/`, plus `latest.json` for
the last successful or partial run. A failed run updates only `latest-failed.json` and never overwrites
the latest useful result. JSON is UTF-8 and is the preferred agent transport.

## Answer the user

For learning mode, lead with a three-to-five-video viewing path, explain why each suits the user's
level, then list useful alternatives. For resource mode, lead with usable project links. For `both`,
present the viewing path first and a distinct resource section second. For every resource result state:

- exact, partial, or inspiration-only fit;
- useful artifacts found and important artifacts not evidenced;
- license status and its exact scope;
- supporting Bilibili links and evidence channels;
- login, access, or human-review limitations.

Then provide additional relevant videos and, if useful, the complete candidate pool in a collapsed or
secondary section. Prefer fewer strong claims over false certainty, but do not hide relevant leads
merely because their license or access still needs human verification.

## Safety

- Never output, upload, summarize, or commit Cookie/API-key values or account identity.
- Never ask for credentials in chat.
- Keep minimal raw evidence by default and omit uploader/commenter identifiers.
- Do not label public files as open source without license evidence.
- Do not claim that missing evidence means a resource does not exist.
