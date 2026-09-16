# A-Stock Lens Project Initialization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Initialize the empty `jinking/a-stock-lens` repository as a tested Python 3.12 project whose structure faithfully enforces the approved A-Stock Lens design boundaries without implementing business algorithms.

**Architecture:** Keep a modular monolith under `src/astock_lens`, with typed domain models and Protocol contracts separating Provider, Normalizer, Factor, Strategy, Signal, and Deep Research responsibilities. Expose only bootstrap-safe entry points: a Typer CLI with a local `doctor` command and a FastAPI health endpoint. Preserve Parquet + DuckDB and the React UI as documented boundaries while deferring data ingestion, factor computation, strategy scoring, and frontend scaffolding.

**Tech Stack:** Python 3.12+, Pydantic 2, pydantic-settings, Typer, FastAPI, PyYAML, DuckDB, PyArrow, Polars, HTTPX, pytest, pytest-cov, Ruff, mypy, uv.

**Spec:** `docs/superpowers/specs/2026-09-16-a-stock-lens-design.md`

## Global Constraints

- The approved precedence is design spec, then `docs/PRODUCT.md`, then `docs/ARCHITECTURE.md`, then `README.md`.
- Architecture remains a local-first modular monolith with pipeline execution and Plugin/Adapter extension points.
- Preserve the dependency direction `Provider → Raw → Normalized → Data Quality Gate → Universe → Factor → Strategy → Market → Signal → Candidate → Watchlist → Deep Research`.
- Strategies must never call AkShare directly, and API/Web code must never recompute factors.
- Python must be `>=3.12`; storage remains Parquet + DuckDB.
- Every time-sensitive model must support `as_of`, and financial observations must support `report_period`, `announce_date`, and `available_at` with `available_at <= as_of`.
- Snapshot lineage reserves `factor_version`, `strategy_version`, and `universe_snapshot`.
- Missing-data states are exactly `VALUE`, `NULL`, `STALE`, `INVALID`, `SOURCE_ERROR`, and `NOT_APPLICABLE`; errors must never silently become zero.
- Watchlist active states are `DISCOVERED`, `WATCH`, `DEEP_RESEARCH`, and `TRACK_SIGNAL`; reserved states are `READY`, `HOLDING`, `EXITED`, and `ARCHIVED`.
- Do not implement real data fetching, factor formulas, strategy algorithms, trading, backtesting, portfolio optimization, ML, real-time quotes, or broker interfaces.
- The deep-research integration is a typed contract and placeholder only; do not import `a-share-deep-research` as a Python dependency.
- React initialization is deferred; `web/README.md` documents the six approved future pages.
- Unknown thresholds and weights remain absent or explicitly documented as deferred; do not invent product rules.

---

### Task 1: Establish Git Baseline and Import the Approved Design

**Files:**
- Create: `README.md`
- Create: `docs/PRODUCT.md`
- Create: `docs/ARCHITECTURE.md`
- Create: `docs/superpowers/specs/2026-09-16-a-stock-lens-design.md`
- Create: `docs/REVIEW_NOTES.md`
- Create: `docs/superpowers/plans/2026-09-16-project-initialization.md`

**Interfaces:**
- Consumes: `/Users/huangjinjin/Downloads/a-stock-lens-design.zip` and the empty GitHub repository `jinking/a-stock-lens`.
- Produces: a `main` root baseline, branch `chore/bootstrap-project`, and an exact working-tree copy of the four approved design artifacts.

- [ ] **Step 1: Reconfirm the remote is still empty**

Run:

```bash
git ls-remote --symref https://github.com/jinking/a-stock-lens.git HEAD
gh repo view jinking/a-stock-lens --json defaultBranchRef,nameWithOwner,url
```

Expected: no remote refs and an empty default branch name.

- [ ] **Step 2: Initialize the repository and publish a neutral PR base**

Run:

```bash
git init -b main
git remote add origin https://github.com/jinking/a-stock-lens.git
git commit --allow-empty -m "chore: initialize repository"
git push -u origin main
git switch -c chore/bootstrap-project
```

Expected: `main` contains only the empty root commit; all project content remains reviewable in the feature branch.

- [ ] **Step 3: Import only approved files, excluding packaged Git metadata**

Use `apply_patch` to create the four files from their corresponding ZIP members. Do not extract `.git/` into the repository.

- [ ] **Step 4: Verify the imported files byte-for-byte**

Run:

```bash
for path in README.md docs/PRODUCT.md docs/ARCHITECTURE.md docs/superpowers/specs/2026-09-16-a-stock-lens-design.md; do
  unzip -p /Users/huangjinjin/Downloads/a-stock-lens-design.zip "$path" | shasum -a 256
  shasum -a 256 "$path"
done
```

Expected: each ZIP/worktree hash pair is identical.

- [ ] **Step 5: Record the only audit note**

Create `docs/REVIEW_NOTES.md` with the observed metadata mismatch: the archived spec says final review is pending, while the current user instruction confirms the package as the formal approved baseline. State that the current instruction resolves the status and that no product rule was changed.

- [ ] **Step 6: Commit the design baseline**

```bash
git add README.md docs
git commit -m "docs: import approved A-Stock Lens design"
```

---

### Task 2: Add Python Packaging, Configuration, and Runtime Directories

**Files:**
- Create: `pyproject.toml`
- Create: `uv.lock`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `Makefile`
- Create: `src/astock_lens/__init__.py`
- Create: `src/astock_lens/settings.py`
- Create: `configs/app.yaml`
- Create: `configs/universe.yaml`
- Create: `configs/providers.yaml`
- Create: `configs/market_regime.yaml`
- Create: `configs/factors/README.md`
- Create: `configs/strategies/value.yaml`
- Create: `configs/strategies/growth.yaml`
- Create: `configs/strategies/garp.yaml`
- Create: `configs/strategies/quality.yaml`
- Create: `configs/strategies/dividend.yaml`
- Create: `configs/strategies/momentum.yaml`
- Create: `configs/strategies/industry_trend.yaml`
- Create: `data/raw/.gitkeep`
- Create: `data/normalized/.gitkeep`
- Create: `data/factors/.gitkeep`
- Create: `data/snapshots/.gitkeep`
- Create: `var/logs/.gitkeep`
- Test: `tests/unit/test_settings.py`

**Interfaces:**
- Consumes: repository root path and `configs/app.yaml`.
- Produces: `load_app_config(path: Path | None = None) -> AppConfig` and a valid installable Python package. The `astock` console entry point is added atomically with its implementation in Task 4.

- [ ] **Step 1: Write the failing configuration test**

```python
from pathlib import Path

from astock_lens.settings import load_app_config


def test_load_app_config_reads_local_storage_paths() -> None:
    config = load_app_config(Path("configs/app.yaml"))

    assert config.app.name == "A-Stock Lens"
    assert config.storage.database == Path("var/astock.duckdb")
    assert config.storage.parquet_root == Path("data")
```

- [ ] **Step 2: Run the focused test and confirm it fails**

Run: `uv run pytest tests/unit/test_settings.py -q`

Expected: FAIL because `astock_lens.settings` does not exist.

- [ ] **Step 3: Add the minimal typed configuration loader**

Implement immutable Pydantic models `AppMetadata`, `StorageSettings`, and `AppConfig`, then load YAML with `yaml.safe_load`. Reject a non-mapping YAML root with `ValueError`; do not swallow parser or validation errors.

```python
def load_app_config(path: Path | None = None) -> AppConfig:
    config_path = path or Path(os.getenv("ASTOCK_CONFIG", "configs/app.yaml"))
    with config_path.open(encoding="utf-8") as stream:
        payload = yaml.safe_load(stream)
    if not isinstance(payload, dict):
        raise ValueError(f"Configuration root must be a mapping: {config_path}")
    return AppConfig.model_validate(payload)
```

- [ ] **Step 4: Add conservative project metadata and dependencies**

Configure Hatchling with the `src` layout. Default runtime dependencies are FastAPI, Uvicorn, Pydantic, pydantic-settings, PyYAML, Typer, and HTTPX. Put DuckDB, PyArrow, and Polars in an optional `data` extra, and AkShare in a separate optional `providers` extra, so bootstrap tests do not install the large data stack. Put pytest, pytest-cov, Ruff, mypy, and types-PyYAML in a `dev` dependency group. Configure Ruff for Python 3.12 and mypy for strict package checking. Exclude `docs` from Ruff so the imported design documents stay byte-identical to the reviewed design package instead of having their embedded Python code fences reformatted.

- [ ] **Step 5: Add configuration files without invented thresholds**

Use only confirmed values. `universe.yaml` may set `min_listing_days: 120`; keep the turnover threshold as `null` with a comment that the exact V1 value is deferred. Strategy YAML files contain only `id`, `enabled`, `version`, `description`, and confirmed `dimensions`; they contain no weights or score thresholds.

- [ ] **Step 6: Run the focused test**

Run: `uv run pytest tests/unit/test_settings.py -q`

Expected: PASS.

- [ ] **Step 7: Commit the project foundation**

```bash
git add pyproject.toml uv.lock .env.example .gitignore Makefile configs data var src/astock_lens/__init__.py src/astock_lens/settings.py tests/unit/test_settings.py
git commit -m "chore: add Python project foundation"
```

---

### Task 3: Define Domain Models and Extension Contracts

**Files:**
- Create: `src/astock_lens/domain/__init__.py`
- Create: `src/astock_lens/domain/enums.py`
- Create: `src/astock_lens/domain/models.py`
- Create: `src/astock_lens/data/__init__.py`
- Create: `src/astock_lens/data/contracts.py`
- Create: `src/astock_lens/factors/__init__.py`
- Create: `src/astock_lens/factors/contracts.py`
- Create: `src/astock_lens/strategies/__init__.py`
- Create: `src/astock_lens/strategies/contracts.py`
- Create: `src/astock_lens/signals/__init__.py`
- Create: `src/astock_lens/signals/contracts.py`
- Create: `src/astock_lens/research/__init__.py`
- Create: `src/astock_lens/research/contracts.py`
- Create: `src/astock_lens/research/models.py`
- Create: package markers for the remaining approved modules under `src/astock_lens/`
- Test: `tests/unit/test_domain_models.py`
- Test: `tests/contract/test_extension_contracts.py`

**Interfaces:**
- Consumes: Pydantic 2 and the exact enums/fields in the approved spec.
- Produces: typed models for time correctness and Protocols named `DataProvider`, `Normalizer`, `Factor`, `StrategyPlugin`, `SignalDetector`, and `DeepResearchAdapter`.

- [ ] **Step 1: Write failing time-correctness and enum tests**

```python
from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from astock_lens.domain.enums import DataStatus, ErrorSeverity, WatchlistState
from astock_lens.domain.models import FinancialObservation


def test_financial_observation_rejects_future_availability() -> None:
    with pytest.raises(ValidationError):
        FinancialObservation(
            symbol="000001.SZ",
            metric="roe",
            value=10.0,
            report_period=date(2026, 6, 30),
            announce_date=date(2026, 8, 20),
            available_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
            as_of=datetime(2026, 8, 19, tzinfo=timezone.utc),
            source="fixture",
        )


def test_architecture_enums_are_explicit() -> None:
    assert {item.value for item in DataStatus} == {
        "VALUE", "NULL", "STALE", "INVALID", "SOURCE_ERROR", "NOT_APPLICABLE"
    }
    assert {item.value for item in ErrorSeverity} == {"P0", "P1", "P2", "P3"}
    assert WatchlistState.DEEP_RESEARCH.value == "DEEP_RESEARCH"
```

- [ ] **Step 2: Write failing contract-surface tests**

```python
from astock_lens.data.contracts import DataProvider, Normalizer
from astock_lens.factors.contracts import Factor
from astock_lens.research.contracts import DeepResearchAdapter
from astock_lens.signals.contracts import SignalDetector
from astock_lens.strategies.contracts import StrategyPlugin


def test_required_contract_methods_are_stable() -> None:
    assert {"health", "fetch"} <= set(DataProvider.__dict__)
    assert {"normalize"} <= set(Normalizer.__dict__)
    assert {"compute"} <= set(Factor.__dict__)
    assert {"required_factors", "eligibility", "score", "explain"} <= set(StrategyPlugin.__dict__)
    assert {"detect"} <= set(SignalDetector.__dict__)
    assert {"submit", "status", "result"} <= set(DeepResearchAdapter.__dict__)
```

- [ ] **Step 3: Run both tests and confirm they fail**

Run: `uv run pytest tests/unit/test_domain_models.py tests/contract/test_extension_contracts.py -q`

Expected: FAIL because the domain and contract modules do not exist.

- [ ] **Step 4: Implement the minimum domain models**

Define string enums for the exact approved states. Define immutable Pydantic models for `FinancialObservation`, snapshot lineage, Provider health/fetch requests, normalization records, factor metadata/results, strategy contexts/results/explanations, signal contexts/results, and research request/job/status/summary. Validate that `available_at <= as_of`; preserve `None` rather than substituting zero.

- [ ] **Step 5: Implement Protocol-only extension contracts**

Each Protocol method has a descriptive docstring and precise parameter and return annotations. Protocols contain no provider call, algorithm, score, threshold, subprocess execution, or fake success value.

Use these public signatures exactly:

```python
class DataProvider(Protocol):
    def health(self) -> ProviderHealth: ...
    def fetch(self, request: FetchRequest) -> RawDataset: ...

class Normalizer(Protocol):
    def normalize(self, dataset: RawDataset, *, as_of: datetime) -> NormalizedDataset: ...

class Factor(Protocol):
    metadata: FactorMetadata
    def compute(self, context: FactorContext) -> FactorResult: ...

class StrategyPlugin(Protocol):
    def required_factors(self) -> set[str]: ...
    def eligibility(self, context: StrategyContext) -> EligibilityResult: ...
    def score(self, context: StrategyContext) -> StrategyResult: ...
    def explain(self, result: StrategyResult) -> Explanation: ...

class SignalDetector(Protocol):
    def detect(self, context: SignalContext) -> SignalResult: ...

class DeepResearchAdapter(Protocol):
    def submit(self, request: ResearchRequest) -> ResearchJob: ...
    def status(self, job_id: str) -> ResearchJobStatus: ...
    def result(self, job_id: str) -> ResearchSummary: ...
```

- [ ] **Step 6: Add package boundaries**

Create package markers for `data/providers`, `data/normalize`, `data/quality`, `data/repository`, `data/storage`, `universe`, `market`, `candidates`, `watchlist`, `research/adapters`, `pipelines`, `jobs`, `api`, `cli`, `backtest`, `portfolio`, and `events`. Only public contracts/models are re-exported.

- [ ] **Step 7: Run focused tests and static typing**

Run:

```bash
uv run pytest tests/unit/test_domain_models.py tests/contract/test_extension_contracts.py -q
uv run mypy src/astock_lens
```

Expected: all tests pass and mypy reports success.

- [ ] **Step 8: Commit the domain boundary**

```bash
git add src/astock_lens tests/unit/test_domain_models.py tests/contract/test_extension_contracts.py
git commit -m "feat: define architecture contracts"
```

---

### Task 4: Add CLI Doctor and FastAPI Health Entrypoints

**Files:**
- Create: `src/astock_lens/cli/app.py`
- Create: `src/astock_lens/api/app.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Test: `tests/unit/test_cli.py`
- Test: `tests/unit/test_api.py`
- Test: `tests/unit/test_import.py`

**Interfaces:**
- Consumes: `load_app_config()` from Task 2.
- Produces: console command `astock`, Typer application `app`, FastAPI factory `create_app()`, and JSON `GET /health` response.

- [ ] **Step 1: Write failing import, CLI, and API smoke tests**

```python
from fastapi.testclient import TestClient
from typer.testing import CliRunner

import astock_lens
from astock_lens.api.app import create_app
from astock_lens.cli.app import app


def test_package_imports() -> None:
    assert astock_lens.__version__


def test_cli_help() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "doctor" in result.stdout


def test_health_route() -> None:
    response = TestClient(create_app()).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "A-Stock Lens"}
```

Split the three tests into their named test files.

- [ ] **Step 2: Run the smoke tests and confirm they fail**

Run: `uv run pytest tests/unit/test_import.py tests/unit/test_cli.py tests/unit/test_api.py -q`

Expected: FAIL because the entry point modules do not exist.

- [ ] **Step 3: Implement the CLI**

Create a Typer app with `no_args_is_help=True` and add `astock = "astock_lens.cli.app:app"` under `[project.scripts]` in `pyproject.toml` in the same change. `doctor` loads local config, checks that Python is at least 3.12, reports configured storage paths, and exits non-zero only when a check fails. It must not fetch market data, connect to an external provider, or create the DuckDB file.

- [ ] **Step 4: Implement the API factory**

`create_app()` returns a FastAPI application titled `A-Stock Lens`; `GET /health` returns exactly `{"status": "ok", "service": "A-Stock Lens"}`. Do not open DuckDB or compute data in the route.

- [ ] **Step 5: Run entrypoint tests and real commands**

Run:

```bash
uv run pytest tests/unit/test_import.py tests/unit/test_cli.py tests/unit/test_api.py -q
uv run astock --help
uv run astock doctor
uv run python -c 'from astock_lens.api.app import create_app; assert create_app().title == "A-Stock Lens"'
```

Expected: all commands exit 0.

- [ ] **Step 6: Commit the bootstrap entrypoints**

```bash
git add pyproject.toml uv.lock src/astock_lens/cli src/astock_lens/api src/astock_lens/__init__.py tests/unit/test_import.py tests/unit/test_cli.py tests/unit/test_api.py
git commit -m "feat: add bootstrap entrypoints"
```

---

### Task 5: Add Maintainer Documentation and Test Scaffolding

**Files:**
- Modify: `README.md`
- Create: `AGENTS.md`
- Create: `docs/DATA_MODEL.md`
- Create: `docs/STRATEGY_SYSTEM.md`
- Create: `docs/DATA_SOURCES.md`
- Create: `docs/DEVELOPMENT.md`
- Create: `docs/TESTING.md`
- Create: `web/README.md`
- Create: `scripts/README.md`
- Create: `tests/integration/README.md`
- Create: `tests/fixtures/README.md`
- Create: `tests/artifacts/README.md`

**Interfaces:**
- Consumes: approved design documents and the commands implemented in Tasks 2–4.
- Produces: a five-minute contributor path and durable instructions for future Codex/AI agents.

- [ ] **Step 1: Expand README without changing product design**

Cover: product purpose, relationship to `a-share-deep-research`, architecture chain, V1 scope and non-goals, current bootstrap status, Python/uv setup, `astock doctor`, tests, quality commands, and the next implementation phase. Keep Candidate distinct from recommendation.

- [ ] **Step 2: Document only confirmed models and deferred details**

`DATA_MODEL.md` records time fields, lineage/version fields, explicit missing states, Watchlist lifecycle, and Research models. `STRATEGY_SYSTEM.md` records seven independent scanners and their common contract. `DATA_SOURCES.md` records bulk sources versus deep-research integration. Where thresholds or schemas are not specified, write `Deferred` or `Not defined in V1`.

- [ ] **Step 3: Add contributor and agent guidance**

`DEVELOPMENT.md`, `TESTING.md`, and root `AGENTS.md` name the authoritative spec, architecture boundaries, setup/quality commands, test layers, and the prohibition on silent data fallbacks. They must direct future work to add a failing test before behavior.

- [ ] **Step 4: Document reserved surfaces**

`web/README.md` lists Today, Screener, Strategy, Stock Profile, Watchlist, and Data Health and explains why React setup is deferred. The test README files state the intended integration, fixture, and independent artifact-validator responsibilities without fake implementations.

- [ ] **Step 5: Run documentation integrity checks**

Run:

```bash
rg -n "Provider.*Normalized|available_at|DEEP_RESEARCH|a-share-deep-research" README.md docs AGENTS.md
rg -n "automated trading|broker API|machine-learning|portfolio optimizer" README.md docs
```

Expected: boundaries and non-goals are present; no document claims the business pipeline is implemented.

- [ ] **Step 6: Commit maintainer documentation**

```bash
git add AGENTS.md README.md docs/DATA_MODEL.md docs/STRATEGY_SYSTEM.md docs/DATA_SOURCES.md docs/DEVELOPMENT.md docs/TESTING.md web scripts tests/integration tests/fixtures tests/artifacts
git commit -m "docs: add maintainer guides"
```

---

### Task 6: Complete Smoke Tests, Verification, and Pull Request

**Files:**
- Modify: test files from Tasks 2–4 if verification exposes a bootstrap defect.
- Create: no new product modules.

**Interfaces:**
- Consumes: the complete initialized project.
- Produces: a clean verification report, final test commit, pushed feature branch, and GitHub pull request.

- [ ] **Step 1: Run the complete test suite**

Run:

```bash
uv run pytest --cov=astock_lens --cov-report=term-missing
```

Expected: all tests pass; coverage is reported for bootstrap modules.

- [ ] **Step 2: Run code-quality gates**

Run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/astock_lens
```

Expected: all commands exit 0.

- [ ] **Step 3: Run required runtime smoke checks**

Run:

```bash
uv run python -c 'import astock_lens; print(astock_lens.__version__)'
uv run astock --help
uv run astock doctor
uv run python -c 'from astock_lens.api.app import create_app; app = create_app(); print(app.title)'
```

Expected: import succeeds, CLI commands exit 0, and API title is `A-Stock Lens`.

- [ ] **Step 4: Commit only verification-driven corrections, if any**

```bash
if ! git diff --quiet; then
  git add src tests pyproject.toml
  git commit -m "test: harden bootstrap verification"
fi
```

Tests are committed with the task that introduces their behavior. This step creates no commit when verification required no correction.

- [ ] **Step 5: Inspect the branch before publication**

Run:

```bash
git status --short
git log --oneline --decorate main..HEAD
git diff --check main...HEAD
git diff --stat main...HEAD
```

Expected: clean working tree, five scoped feature commits plus at most one verification-fix commit, and no whitespace errors.

- [ ] **Step 6: Push and open the PR**

```bash
git push -u origin chore/bootstrap-project
gh pr create \
  --base main \
  --head chore/bootstrap-project \
  --title "chore: bootstrap A-Stock Lens project" \
  --body-file .superpowers/sdd/2026-09-16-project-initialization/pr-body.md
```

The PR body lists what was added, explicitly states that no real provider/factor/strategy/deep-research/frontend behavior was implemented, includes exact verification results, records the spec-status metadata note, and recommends implementing the first vertical slice next.
