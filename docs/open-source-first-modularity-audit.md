# v1 Open-Source-First and Modularity Audit

## Decision rule

For each substantial module, investigate official documentation, upstream issues, and maintained
open-source implementations before writing code. Record one decision:

- **Adopt**: use the maintained project directly.
- **Wrap**: use it behind a project-owned port so it remains replaceable.
- **Reference**: reuse the design, not the dependency or code.
- **Reject**: document why it is unsuitable before writing the smallest local implementation.

Evaluate license compatibility, maintenance, Windows support, dependency weight, privacy, security,
network behavior, and replacement cost. Repeat the review when a module changes materially or an
integration fails in production.

## Current external decisions

| Area | Existing project | Decision | Reason |
|---|---|---|---|
| Bilibili metadata, subtitles, and bounded comments | [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Wrap | Its maintained Bilibili extractor already handles login-aware subtitle and comment structures. Keep it behind `EvidenceReader`; do not duplicate its protocol implementation. |
| Managed browser session | [Playwright](https://playwright.dev/python/docs/auth) | Wrap | Browser contexts and reusable authentication state are established upstream capabilities. Keep credentials in ignored project state and keep Playwright out of the pipeline contract. |
| Windows bootstrap and private Python | [uv](https://github.com/astral-sh/uv) | Adopt | Pinned standalone releases and private Python installation reduce system-Python and editable-install failures. |
| GitHub license evidence | [GitHub REST license endpoints](https://docs.github.com/en/rest/licenses/licenses) | Wrap | The official endpoint identifies a repository license using Licensee and SPDX names, while explicitly not proving dependency or whole-project license scope. |
| Optional public metasearch | [SearXNG](https://github.com/searxng/searxng) | Reference now; adapter later | Its engine model is useful for a future `SearchProvider`, but embedding or requiring a SearXNG server would raise first-use complexity. |
| General Python plugin framework | [pluggy](https://github.com/pytest-dev/pluggy) | Reject for v1 | It is mature, but current built-in providers need only typed `Protocol` ports. Add a plugin manager only when third-party provider discovery becomes a real requirement. |

## What is already modular

- Pydantic contracts separate intent, queries, candidates, evidence, resources, events, and outcomes.
- Planner, ranker, resource extractor, and report rendering are deterministic and offline-testable.
- Candidate discovery, evidence reading, persistence, extraction, and verification have protocols.
- HTTP transport is injected into resource verification for deterministic tests.
- Bilibili requests share one run budget and circuit state.
- Main source and bundled runtime currently match byte-for-byte, and tests guard against drift.

## Findings

### P1: adapters depend on orchestration errors

`evidence_reader.py`, `search_session.py`, and `resource_verification.py` import exception classes
from `pipeline.py`. This reverses the desired dependency direction: adapters should implement ports
without importing the coordinator.

**Change:** move shared failure types to a small `errors.py` or contract-level module. Let the
pipeline and adapters depend on that shared module. Do not add an external framework for this.

### P1: the planner port is owned by the pipeline

`QueryPlanner` lives in `pipeline.py`, while all other replaceable boundaries live in `ports.py`.

**Change:** move `QueryPlanner` to `ports.py`. Keep `pipeline.py` limited to orchestration and outcome
policy.

### P1: checkpoints save deep evidence but cannot load it through the port

`CheckpointStore` can load candidates, but evidence and resources are write-only. The README promises
stage reuse, yet the v1 pipeline cannot directly restore completed deep reads or resource checks from
this contract.

**Change:** define keyed `load_evidence` and `load_resources` methods with freshness and retention
semantics. Reuse completed stages before spending a network budget. Test cache hit, expiry, partial
records, and privacy-minimized records offline.

### P1: direct project leads enter through an evidence-shaped workaround

The CLI converts `--resource-url` values into seeded `EvidenceRecord` objects because the pipeline has
no project-discovery boundary. This mixes “a discovered project lead” with “evidence read from a
video.”

**Change:** introduce either a small `ResourceDiscoverer` port or typed initial resources. Do not
adopt a general plugin framework yet. A future SearXNG, GitHub, Gitee, or OSHWHub adapter should emit
the same resource-lead contract.

### P2: the CLI combines translation and dependency construction

`cli.py` parses commands, infers intent, normalizes seed URLs, builds concrete adapters, runs the
pipeline, and formats the process summary. It is still manageable, but it will become the wrong place
to add a website or another agent host.

**Change:** add a structured `IntentProfile` JSON input and move dependency construction into a small
application factory. Keep argparse as a thin transport adapter.

### P2: provider implementations will outgrow one verifier file

`resource_verification.py` currently contains transport, GitHub verification, generic verification,
and routing. Splitting it now would add files without user value, but a second platform-specific
verifier will make the boundary worthwhile.

**Change trigger:** when adding the next real provider, create `verifiers/` with a router, shared HTTP
port, and one module per platform. Do not pre-build empty provider modules.

### P2: source duplication is controlled, not eliminated

The canonical source and distributable Skill runtime currently match, but both are committed. Tests
catch drift after it happens.

**Change:** make `src/bhka` canonical and generate the distributable runtime or wheel during release.
Use the existing uv/wheel path instead of inventing another installer. Keep the Skill independently
installable for Codex and OpenCode.

### P2: v1 still imports legacy application modules

The v1 CLI, login, and evidence reader reuse `bhka.config`, `bhka.source`, `bhka.models`, and
`bhka.browser_login`. Reuse is preferable to copying working code, but these modules need explicit
adapter status so a future removal of the legacy CLI does not break v1 accidentally.

**Change:** rename or move reusable pieces only when unifying `bhka` and `bhka-v1`; avoid a cosmetic
rewrite before that migration is planned and tested.

## Recommended sequence

1. Move shared errors and `QueryPlanner` out of the pipeline.
2. Complete cache load contracts and demonstrate real deep-read reuse.
3. Add structured intent JSON and a dependency-construction factory.
4. Add a typed project-lead/resource-discovery boundary.
5. Generate the Skill runtime from canonical source during release.
6. Unify `bhka` and `bhka-v1` after compatibility tests.
7. Consider pluggy or another plugin manager only after external provider installation is required.

Each step must begin with an updated open-source review, preserve Windows-first installation, use
offline tests, and avoid new Bilibili requests during automated validation.
