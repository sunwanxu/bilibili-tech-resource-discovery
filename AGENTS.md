# Repository Guidelines

## Project Structure & Module Organization

The package uses a narrow pipeline. `src/bhka/source.py` is the only Bilibili-facing adapter and converts `yt-dlp` output into models from `src/bhka/models.py`. `src/bhka/analyzers.py` contains interchangeable OpenAI and heuristic analyzers; neither should fetch platform data. `src/bhka/storage.py` persists source evidence under `data/raw/`, analysis JSON under `data/processed/`, and Markdown under `reports/`. Research findings and decisions live in `docs/`. Tests use synthetic data and must not contact Bilibili.

## Build, Test, and Development Commands

Create the Windows environment with `python -m venv .venv`, then install using `.\.venv\Scripts\python -m pip install -e ".[dev]"`. Run all tests with `.\.venv\Scripts\python -m pytest`; run one test with `.\.venv\Scripts\python -m pytest tests/test_core.py::test_normalize_bvid_accepts_url_and_id`. Check code with `.\.venv\Scripts\ruff check .`. Analyze a video using `.\.venv\Scripts\bhka analyze <BVID> --project-root .`.

## Coding Style & Naming Conventions

Ruff targets Python 3.11 with a 100-character line limit, as configured in `pyproject.toml`. Use Pydantic models for persisted contracts and protocols for replaceable data-source/analyzer boundaries. Missing upstream evidence must remain `None` or empty and be explained in `evidence_limitations`; do not map an unrelated metric into a required field.

## Testing Guidelines

Pytest discovers tests under `tests/`. Unit tests must remain deterministic and offline. Network experiments are manual, low-rate checks against explicitly chosen BVIDs and must retain raw responses for later analysis.

## Secrets and External Requests

Copy `.env.example` to `.env`; never commit API keys or cookies. Keep timeout, retry, and request spacing configurable. Do not add bulk crawling, authentication bypasses, or undocumented protocol implementations. Comments remain opt-in because upstream pagination can produce unbounded requests.
