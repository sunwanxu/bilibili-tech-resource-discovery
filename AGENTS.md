# Repository Guidelines

## Project Structure & Module Organization

The package uses a staged pipeline. `src/bhka/v1/contracts.py` owns persisted and cross-module contracts; `ports.py` owns replaceable boundaries; `planner.py`, `ranking.py`, `resource_extraction.py`, and `reporting.py` remain deterministic; network access belongs only in search, evidence-reader, login, or resource-verifier adapters. `pipeline.py` coordinates these modules but must not absorb their implementation details. The legacy `src/bhka/source.py` remains the single yt-dlp adapter for compatibility. The distributable Skill runtime mirrors `src/bhka`; tests must detect drift. Research findings and decisions live in `docs/`. Tests use synthetic data and must not contact Bilibili.

## Open-Source-First Engineering

Before designing a subsystem, adding a substantial feature, or fixing a complex integration failure, search official documentation, upstream issues, and maintained open-source implementations. Evaluate each candidate for license compatibility, maintenance, Windows support, dependency weight, privacy, security, and replaceability. Record the decision as one of: adopt, wrap, reference, or reject. Write a new implementation only when no suitable option exists, and then implement the smallest replaceable module with offline tests and a short explanation of why existing options were insufficient.

Repeat this review at each relevant stage: product and architecture discovery, per-module design, integration failures, search/ranking changes, packaging, authentication, caching, UI, and evaluation. Prefer official standards and existing adapters over custom protocols. Do not introduce an open-source dependency merely because it exists; wrap external capabilities behind project-owned protocols so they can be replaced without changing the pipeline.

## Module Boundaries

Keep intent intake, query planning, candidate discovery, normalization, ranking, Bilibili evidence reading, resource extraction, resource verification, caching, request policy, and reporting separate. Each module should have one primary reason to change and exchange typed contracts rather than raw third-party payloads or ad hoc dictionaries. Ranking must not fetch data; reporting must not make network requests; adapters must not decide product-level value; cache and circuit-breaker policy must apply across the run rather than being reimplemented per adapter.

When adding a provider, implement an existing port or introduce the smallest general port needed by at least one real use case. Avoid domain-specific allowlists and blacklists in the core. A failure in one candidate or provider must not discard completed work from other modules. Preserve checkpoints and explicit partial-success semantics at module boundaries.

## Build, Test, and Development Commands

Create the Windows environment with `python -m venv .venv`, then install using `.\.venv\Scripts\python -m pip install -e ".[dev]"`. Run all tests with `.\.venv\Scripts\python -m pytest`; run one test with `.\.venv\Scripts\python -m pytest tests/test_core.py::test_normalize_bvid_accepts_url_and_id`. Check code with `.\.venv\Scripts\ruff check .`. Analyze a video using `.\.venv\Scripts\bhka analyze <BVID> --project-root .`.

## Coding Style & Naming Conventions

Ruff targets Python 3.11 with a 100-character line limit, as configured in `pyproject.toml`. Use Pydantic models for persisted contracts and protocols for replaceable data-source/analyzer boundaries. Missing upstream evidence must remain `None` or empty and be explained in `evidence_limitations`; do not map an unrelated metric into a required field.

## Testing Guidelines

Pytest discovers tests under `tests/`. Unit tests must remain deterministic and offline. Network experiments are manual, low-rate checks against explicitly chosen BVIDs and must retain raw responses for later analysis.

## Secrets and External Requests

Copy `.env.example` to `.env`; never commit API keys or cookies. Keep timeout, retry, and request spacing configurable. Do not add bulk crawling, authentication bypasses, or undocumented protocol implementations. Comments remain opt-in because upstream pagination can produce unbounded requests.
