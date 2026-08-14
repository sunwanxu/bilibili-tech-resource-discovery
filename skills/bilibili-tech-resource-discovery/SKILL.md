---
name: bilibili-tech-resource-discovery
description: Discover and prioritize usable open-source technical projects from a natural-language need by combining public web indexes, Bilibili evidence, and open-project platforms; verify code, hardware artifacts, access, and license scope; then connect supporting videos, descriptions, bounded comments, and subtitles. Use when a user wants source code, PCB projects, competition solutions, build references, technical tutorials, implementation ideas, or hidden resources mentioned around Bilibili videos. Also use when setting up or troubleshooting the local Bilibili login needed by this workflow.
---

# Bilibili Technical Resource Discovery

Give the user a working result before optimizing optional features. Treat first-run onboarding as part
of the task, not as homework for the user.

Treat usable source code, hardware projects, and engineering files as the primary result. Treat
Bilibili videos as discovery channels, explanations, and supporting evidence. Do not optimize for
video count when the user's real goal is a reusable project.

## Locate the bundled runtime

Treat the directory containing this `SKILL.md` as `<skill>`. The portable runtime and its private
state live under `<skill>/runtime`; no external companion repository is required.

Use the bundled executable. The default private environment is `.venv`. If
`<skill>/runtime/.venv-path` exists, read its single directory name and use that environment instead;
the installer writes this pointer only when a running Windows agent has locked an older launcher.

- Windows: `<skill>\runtime\<environment>\Scripts\bhka.exe`
- macOS/Linux: `<skill>/runtime/<environment>/bin/bhka`

Treat that exact absolute executable path as `<bhka>`. Never invoke a bare `bhka` from `PATH`; it may
resolve to an older installation. Confirm `<bhka> --version` reports `bhka 0.6.0` before a smoke test.
Use `<skill>/runtime` whenever a command requests `--project-root`. During source development only,
an explicitly supplied external `bilibili-hidden-knowledge-agent` repository may replace the bundled
runtime.

## Complete first-run onboarding

Read [references/onboarding.md](references/onboarding.md) whenever preflight fails, login has not
been configured, browser-cookie access fails, or the user asks how to install or log in.

Use the single portable installation entry point:

```text
python <skill>/scripts/install.py --agent auto
```

When the current host is known, pass `--agent codex` or `--agent opencode`; the user should never need
to choose. The installer copies the complete folder to the host's standard global Skill location,
creates the bundled runtime, preserves an existing managed login during updates, and opens an
isolated Edge window only when a new login is needed. Tell the user only to complete normal Bilibili
login in that window. Credentials stay local and must never be pasted into chat. Do not ask the user
to install Firefox, export cookies, choose a browser profile, or run diagnostic commands during the
normal path.

If the installer exits nonzero, keep its concise error and perform the matching recovery step from
the onboarding reference yourself. Do not turn internal diagnostics into user homework.

Never claim that login is valid merely because configuration exists. A successful Bilibili request is
the final verification. If authenticated content cannot be read, continue in public-data mode and
label the evidence gap instead of blocking the entire search.

Plain `status` is a local configuration check: a complete configuration that still needs network
verification returns success and prints `VERIFY-NEEDED`. It identifies the project-managed `.auth`
session separately from an externally supplied Netscape cookie file.

Use `--no-login` only for CI or an offline installation test. The portable installer keeps previous
Skill copies outside the active directory and excludes Python caches and credentials.

## Understand the request

Infer these fields from the conversation:

- goal or artifact to build;
- current skill level;
- platform, hardware, language, or tool constraints;
- desired resource types such as source code, PCB, tutorial, design comparison, or troubleshooting;
- whether the user requires explicit open source or also wants uncertain leads.

Ask at most one concise question only when a missing answer would materially change the search.
Otherwise state a reasonable assumption and proceed.

## Run bounded discovery

Interpret the request yourself before searching. The user supplies only the natural-language need;
do not expose query counts, CLI flags, or candidate limits unless they ask for diagnostics.

Use multi-source discovery for a normal run:

1. Search GitHub, Gitee, OSHWHub/JLC Open Source, and relevant official project sites directly with
   four to six resource-oriented queries. Do not require a project to originate from a video.
2. Use ordinary web search to find 15-40 public Bilibili video URLs with four to six precise
   `site:bilibili.com/video` queries. Prefer candidates whose snippets or descriptions expose
   repositories, hardware projects, project names, or downloadable engineering artifacts.
3. Keep Bilibili internal search disabled during normal discovery. Use one precise internal query
   only for an explicit, bounded diagnostic when public indexes are unavailable or demonstrably
   insufficient. Never use repeated internal queries as the primary discovery path.
4. Pass public Bilibili URLs with repeated `--candidate-url` and direct project links with repeated
   `--resource-url`. These are internal host-AI details, not user inputs.

When `FIRECRAWL_API_KEY` is already configured in the bundled runtime, leave `--web-search auto` in
place. The runtime then performs five shallow, bounded public-web queries before direct Bilibili
discovery and contributes public Bilibili URLs plus direct project links to the same evidence pool. Treat this
as an optional coverage enhancement: never require a Firecrawl key for normal use, never put the key
in a command line or report, and continue with existing sources when the provider is unavailable.
Use `--web-search off` for offline tests or when the user explicitly disables the provider.

Example internal invocation:

```text
<bhka> discover "<natural-language requirement>" --query "<precise topic>" --candidate-url "<Bilibili URL>" --resource-url "<repository URL>" --max-candidates 80 --deep 8 --comments --bilibili-search off --project-root <skill>/runtime
```

Keep `--bilibili-search off` for normal runs; this is the runtime default. Use `on` only for a
deliberate, bounded internal-search diagnostic. Candidate breadth and deep inspection are separate:
return many relevant candidate links, but fetch subtitles and comments only for the best bounded set.

Do not ask the user to invent keywords or identify the official problem title. Use the host AI's
research and reasoning to derive them. If no explicit query plan is supplied, the runtime uses a
deterministic entity-preserving fallback. If ordinary web search is unavailable, continue with
bounded Bilibili discovery and state that the public-web and direct-repository coverage is missing.

Reduce the limits for smoke tests or after rate limiting. Do not implement bulk crawling,
authentication bypass, CAPTCHA automation, or undocumented protocols. Keep comments bounded.

Create one deduplicated resource pool from direct web results, video descriptions, bounded comments,
and subtitles. Recognize full URLs and bare repository addresses such as `github.com/owner/repo`.
When evidence mentions a distinctive project name without a URL, perform a precise public-web search
for that name. Merge the same resource across channels and retain every evidence origin and
supporting video.

For a normal broad request, aim to present 10-20 useful resource links and 15-30 supporting or
alternative video links when the evidence actually supports that many. Do not pad the answer with
weakly related results to reach a quota. If fewer survive verification, return the smaller honest set
and say which discovery channel was thin.

Rank resources before videos. Prefer, in order: accessible projects with verified licenses and
matching artifacts; accessible public source without verified licenses; platform projects whose
license terms need review; restricted shared files; and unverified leads. Evaluate schematic, PCB,
BOM, Gerber, firmware/source, documentation, hardware validation, and license independently. A video
with a usable project link should normally outrank a slightly more popular or keyword-dense video
without reusable artifacts.

Preserve the user's own high-information entities during query expansion: years, A-Z problem
letters, quoted phrases, model numbers, acronyms, platform/tool names, and non-resource topic terms.
Separate generic resource intents such as source code, tutorials, project files, and design
comparisons instead of replacing the topic with a fixed domain vocabulary. Avoid duplicated terms. Reports distinguish
queries that succeeded, actually failed, and were skipped by a circuit breaker; include the stopped
query and stop reason.

Run any explicitly enabled internal queries adaptively. Start with the most precise query and stop expanding once there are enough
unique candidates for the requested deep-inspection limit. Before deep inspection, require year,
problem-letter, and quoted-phrase anchors when the request contains them. Apply a generic
topic-overlap threshold to reject cross-domain results; do not encode one task's positive or
negative vocabulary into the core filter. Treat models and acronyms as alternative relevance signals,
not a requirement that every term appear in the title or description. Send explicit
`--candidate-url` items directly to bounded deep inspection without a separate Bilibili preview
request. Enable the strict rejection gate only when more than 30 candidates compete for the
shortlist. Never reject every candidate and then restore the same set as a fallback.

Reuse the local seven-day cache for identical natural-language requirements, BVIDs, previews, and
explicitly enabled internal queries. Cached subtitles and comments are stored locally without author
identifiers. A repeated run should reuse completed evidence rather than request it from Bilibili
again. Prefer `discover --summary-json` for agent-to-agent transport; it emits UTF-8 JSON containing
counts and result URLs without requiring the agent to parse Markdown or guess a report directory.

Space direct Bilibili requests across authentication, search, preview, and deep-inspection phases;
do not rely only on an extractor's per-command delay. Increase spacing gradually within a run and
keep retries low. This reduces avoidable 412 responses without reducing public-web or repository
discovery breadth.

If Bilibili returns HTTP 412, stop all remaining direct Bilibili requests for the run. Continue only
ordinary public-web discovery and direct repository inspection. Preserve public-web video URLs as
uninspected candidates and independently discovered repositories as direct resources; do not imply
that Bilibili internal search or video inspection succeeded. Do not deep-inspect Bilibili candidates
during the cooldown.

The HTTP 412 circuit breaker is run-wide, not search-only. Skip candidate preview, metadata,
description, subtitles, comments, multipart listing, and deep inspection after it opens. Preserve
only candidates and evidence completed beforehand. Honor the persisted local safety cooldown; it is
a client recommendation, not an official Bilibili countdown and not evidence that login failed.
Use the lightweight adaptive schedule: 2 minutes after the first 412, 5 minutes after a second 412
within two hours, and at most 10 minutes after further consecutive 412 responses. Reset to two
minutes after two hours without another 412. Never activate cooldown from ordinary successful,
empty, or repeated searches; only a confirmed HTTP 412 can create it. Continue public-web and
open-project discovery throughout the cooldown.

Tell the user which phase is running: preflight, keyword expansion, candidate search, ranking, deep
inspection, external-link verification, or report writing. If a command is still running, provide a
short progress update at least once per minute so first-time users do not mistake normal work for a
freeze.

Use the generated JSON and Markdown as evidence, then have the AI synthesize a user-facing answer.
Do not pretend to have watched the complete video. Distinguish metadata, description, comment,
subtitle, repository, and human-review evidence.

For a privacy-preserving single-video smoke test, use `<bhka> analyze <BV> --summary-json`; it emits
counts and standardized warning/error codes without subtitle text, comment text, or account identity.
Single-video analysis does not retain raw subtitle/comment evidence unless `--retain-raw` is supplied.
Retained raw evidence is normalized and omits uploader and commenter identifiers.

## Evaluate resources

Read [references/evidence-standard.md](references/evidence-standard.md) before presenting final
open-source or completeness claims.

For every recommended item, include:

- direct code, project, document, or cloud link first;
- why the resource matches the user's need and level;
- supporting Bilibili source links when available;
- open-source status with evidence;
- useful artifacts found and important artifacts not evidenced;
- limitations, login requirements, or manual checks;
- whether it is an exact solution, partial solution, or design inspiration.

Keep license scope per resource. A verified component repository license must not raise the whole
competition package to verified open source when hardware, vision code, cloud files, or other key
parts remain unlicensed or inaccessible. Mark the project-level scope incomplete in that case.

Prefer five to ten strong usable resources. Then list the videos that explain, validate, or reveal
those resources. Put relevant videos with no usable project evidence in a secondary section. Compare
genuinely different technical routes when the user wants broader design ideas. Treat Bilibili as an
important evidence channel, not the only place where code may be discovered.

End with restricted or unverified resources in a separate section. Include the expanded keywords,
coverage blind spots, and stopping reason so the user can judge search breadth.

## Protect the user

- Never print, quote, summarize, upload, commit, or place Cookie/API-key values in reports.
- Never ask the user to paste a raw Cookie into chat.
- Never copy another person's login session into the package.
- Do not recommend unknown cookie-export extensions. Prefer browser-session reading; if a file is
  necessary, explain that it is equivalent to a login credential and should be stored locally.
- Do not mark public files as licensed open source without license evidence.
- Do not turn absence of evidence into a definitive claim that an artifact does not exist.
