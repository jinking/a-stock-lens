# Full-Market Bootstrap Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fragile full-market bootstrap execution path with a batch-capable, bounded, transport-timeout-aware, checkpointed and observable design that proves reliability on fake/100/500-symbol gates before any full-market run.

**Architecture:** Introduce a bootstrap-specific source boundary with batch-first and per-symbol fallback semantics. Move timeout responsibility to the actual transport layer, replace submit-all/sequential-result waiting with a bounded completion-order scheduler, persist per-symbol progress to staging/manifest state, and compact once into canonical raw bars. Full-market execution is forbidden until fake-source, 100-symbol, and 500-symbol gates pass.

**Tech Stack:** Python >=3.12, Pydantic 2.x, Typer, concurrent.futures or equivalent bounded scheduler primitives, pytest, Ruff, mypy, existing AkShare/WeStock providers and raw CSV landing model.

**Spec:** `docs/superpowers/specs/2026-09-18-full-market-bootstrap-redesign.md`

## Global Constraints

- Preserve all existing Universe product thresholds.
- Preserve Research Universe semantics.
- Do not force a 2,500-symbol quota.
- Do not create Candidate Qualification production thresholds.
- Do not enable production Candidate publishing.
- Do not add a new external provider without owner approval.
- Do not describe a `Future.result(timeout=...)` as a network timeout.
- Do not run the full market before Task 10 explicitly passes.
- Every behavioral change follows TDD.
- Every task ends with focused verification, commit, and push.
- Commit messages and project docs remain Chinese.
- If a STOP GATE triggers, stop and report evidence instead of inventing a workaround.

---

## File Structure

### Create

- `src/astock_lens/data/bootstrap_sources.py`
  - bootstrap source protocols and capability models.
- `src/astock_lens/data/bootstrap_scheduler.py`
  - bounded in-flight fallback scheduler.
- `src/astock_lens/data/bootstrap_checkpoint.py`
  - run manifest, staging parts, resume logic.
- `src/astock_lens/data/bootstrap_progress.py`
  - progress events and heartbeat rendering.
- `tests/unit/test_bootstrap_scheduler.py`
- `tests/unit/test_bootstrap_checkpoint.py`
- `tests/unit/test_bootstrap_batch_fallback.py`
- `tests/unit/test_bootstrap_progress.py`
- `tests/stress/test_bootstrap_scale_properties.py`
- `docs/BOOTSTRAP-SOURCE-PROBE-2026-09-18.md`

### Modify

- `src/astock_lens/data/bootstrap.py`
- `src/astock_lens/data/providers/akshare_provider.py`
- `src/astock_lens/data/sync.py`
- `src/astock_lens/cli/app.py`
- existing bootstrap unit/integration tests
- `docs/RETROSPECTIVE-2026-09-18-full-market-bootstrap.md`
- `docs/ROADMAP.md`
- `docs/REVIEW_NOTES.md`
- `.workbuddy/memory/2026-09-18.md`

---

### Task 1: Pin the Unresolved Timeout Bug With Failing Tests

**Files:**
- Create: `tests/unit/test_bootstrap_scheduler.py`
- Modify: `tests/unit/test_bootstrap_scan_cost.py`
- Modify: `docs/RETROSPECTIVE-2026-09-18-full-market-bootstrap.md`

**Interfaces:**
- Consumes current `land_bar_chunks()` behavior.
- Produces regression tests describing the required bounded scheduler semantics.

- [ ] **Step 1: Add the all-workers-hang reproduction**

Use 50 symbols, 6 workers, and a fake fetcher whose first 6 started operations block much longer than the test deadline.

Required shape:

```python
def test_all_inflight_workers_hanging_does_not_serialize_timeout_budget():
    symbols = tuple(f"{i:06d}.SZ" for i in range(50))
    fetcher = FirstNHangFetcher(n=6, sleep_seconds=30)

    started = time.perf_counter()
    result = run_fallback_scheduler(
        ...,
        max_inflight=6,
        operation_timeout_seconds=0.2,
    )
    elapsed = time.perf_counter() - started

    assert elapsed < 2.0
```

Under the current sequential `future.result(timeout=...)` implementation, this test should fail or expose timeout accumulation.

- [ ] **Step 2: Add a leaked-running-work test**

Instrument the fake fetcher with `active`, `max_active`, `started`, `finished`. After scheduler returns, assert the architecture-defined post-timeout state. If threads cannot be terminated, this test should demonstrate why thread-based timeout is insufficient.

- [ ] **Step 3: Run RED**

```bash
uv run pytest tests/unit/test_bootstrap_scheduler.py -v
```

Expected: fail against current code.

- [ ] **Step 4: Correct the retrospective conclusion**

Record:

```text
Root causes 1–3 were implementation defects.
Root cause 4 exposed an execution-boundary flaw:
Future timeout was used where transport timeout/process isolation was required.
The per-symbol-only bootstrap path also remains an architectural scale risk.
```

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_bootstrap_scheduler.py \
        tests/unit/test_bootstrap_scan_cost.py \
        docs/RETROSPECTIVE-2026-09-18-full-market-bootstrap.md
git commit -m "测试：复现冷启动超时串行累加与挂起任务残留"
git push
```

---

### Task 2: Introduce Bootstrap Source Contracts

**Files:**
- Create: `src/astock_lens/data/bootstrap_sources.py`
- Create: `tests/unit/test_bootstrap_batch_fallback.py`

**Interfaces:**

```python
class BootstrapBatchRequest(DomainRecord):
    symbols: tuple[str, ...]
    start_date: date
    end_date: date
    as_of: datetime

class BatchFetchResult(DomainRecord):
    datasets: tuple[RawDataset, ...]
    missing_symbols: tuple[str, ...]
    source_name: str

class BatchMarketBarSource(Protocol):
    def fetch_recent_bars(
        self, request: BootstrapBatchRequest
    ) -> BatchFetchResult: ...

class SymbolBarFallbackSource(Protocol):
    def fetch_symbol_bars(
        self,
        symbol: str,
        *,
        as_of: datetime,
        start_date: date,
        end_date: date,
    ) -> RawDataset: ...
```

- [ ] **Step 1: Write contract tests**

Pin:
- batch source may return partial coverage;
- missing symbols are explicit;
- fallback source is one-symbol-at-a-time;
- no source is allowed to fabricate an empty VALUE dataset.

- [ ] **Step 2: Implement only the contracts/models**

Do not wire providers yet.

- [ ] **Step 3: Verify**

```bash
uv run pytest tests/unit/test_bootstrap_batch_fallback.py -v
uv run mypy src/astock_lens/data/bootstrap_sources.py
```

- [ ] **Step 4: Commit**

```bash
git add src/astock_lens/data/bootstrap_sources.py \
        tests/unit/test_bootstrap_batch_fallback.py
git commit -m "数据：建立批量优先与单标的补缺的启动数据源契约"
git push
```

---

### Task 3: Probe Real Batch Capabilities Before Coding a Provider

**Files:**
- Create: `docs/BOOTSTRAP-SOURCE-PROBE-2026-09-18.md`
- Modify: `docs/ROADMAP.md`

**This task is investigation only. No provider implementation is allowed before evidence exists.**

- [ ] **Step 1: Inspect AkShare capabilities**

Using the installed AkShare version and locally available callable inventory/documentation, search for endpoints that can return recent A-share bars in broad/batch form.

Record:
- endpoint/function name;
- whether it is per-symbol or market-wide;
- fields;
- history depth;
- network call shape;
- whether start/end dates are supported.

- [ ] **Step 2: Inspect WeStock capabilities**

Use CLI help/discovery only:

```bash
tools/bin/westock --help
tools/bin/westock <relevant-command> --help
```

Search for recent price/history/batch/all-market capabilities.

- [ ] **Step 3: Inspect existing repository providers**

```bash
rg -n "daily|bar|history|quote|行情|K线" src tools docs
```

- [ ] **Step 4: Write evidence table**

The document must contain:

```text
Source
Capability
Batch breadth
Date range support
Observed row count
Observed request count
Suitable as bootstrap primary? yes/no
Reason
```

- [ ] **Step 5: Apply decision rule**

Choose batch primary only if evidence proves it can materially reduce remote request count while preserving symbol/date/amount fields.

If none qualifies, write exactly:

```text
NO_BATCH_PRIMARY_AVAILABLE
```

This is a valid outcome.

- [ ] **Step 6: Commit**

```bash
git add docs/BOOTSTRAP-SOURCE-PROBE-2026-09-18.md docs/ROADMAP.md
git commit -m "调研：记录全市场启动行情批量数据源能力"
git push
```

---

### Task 4: Put Timeout at the Real Transport Boundary

**Files:**
- Modify: `src/astock_lens/data/providers/akshare_provider.py`
- Possibly create: `src/astock_lens/data/http_transport.py`
- Modify/create provider tests.

**Interfaces:**

If the active transport supports explicit timeouts, expose something equivalent to:

```python
class TransportTimeouts(DomainRecord):
    connect_seconds: float
    read_seconds: float
```

- [ ] **Step 1: Prove current transport limitation**

Write a focused test/probe showing whether `_live_transport` can actually interrupt a blocked source call. Do not infer this from `Future.result()`.

- [ ] **Step 2: Choose exactly one valid implementation path**

**Path A — controllable transport:** implement explicit connect/read timeouts at actual I/O boundary.

**Path B — uncontrollable library call:** document:

```text
AKSHARE_FALLBACK_REQUIRES_PROCESS_ISOLATION
```

and require killable worker processes for the fallback scheduler.

- [ ] **Step 3: Verify wall-clock bound**

The test must demonstrate a bounded elapsed time around an intentionally non-returning transport.

- [ ] **Step 4: Commit**

```bash
git add src/astock_lens/data/providers/akshare_provider.py tests
# add src/astock_lens/data/http_transport.py only if Path A actually requires it
git commit -m "数据：把行情超时边界下沉到真实网络调用"
git push
```

---

### Task 5: Implement a Bounded Completion-Order Fallback Scheduler

**Files:**
- Create: `src/astock_lens/data/bootstrap_scheduler.py`
- Modify: `tests/unit/test_bootstrap_scheduler.py`

**Interfaces:**

```python
class FallbackAttempt(DomainRecord):
    symbol: str
    status: DataStatus
    dataset: RawDataset | None = None
    error: str | None = None

class SchedulerStats(DomainRecord):
    submitted: int
    completed: int
    timed_out: int
    source_errors: int
    max_inflight_observed: int

def fetch_symbols_bounded(
    *,
    source: SymbolBarFallbackSource,
    symbols: Sequence[str],
    as_of: datetime,
    start_date: date,
    end_date: date,
    max_inflight: int,
    operation_timeout_seconds: float,
    on_result: Callable[[FallbackAttempt], None],
) -> SchedulerStats:
    ...
```

- [ ] **Step 1: Test completion order**

A slow first symbol must not block a fast later symbol from being checkpointed.

- [ ] **Step 2: Test max in-flight**

Assert `fetcher.max_active <= max_inflight` for 5,300 fake symbols.

- [ ] **Step 3: Test all workers hang**

Use Task 1 reproduction. Scheduler verdict must be bounded by transport/process isolation semantics, not `N * timeout`.

- [ ] **Step 4: Test request upper bound**

For an all-success source and a sufficiently-wide first round:

```text
requests <= number_of_symbols
```

- [ ] **Step 5: Implement scheduler**

Use completion-order primitives and a strict bounded active set. Do not submit 5,300 futures at once.

- [ ] **Step 6: Verify and commit**

```bash
uv run pytest tests/unit/test_bootstrap_scheduler.py -v
git add src/astock_lens/data/bootstrap_scheduler.py \
        tests/unit/test_bootstrap_scheduler.py
git commit -m "数据：用有界完成顺序调度替代逐标的串行等待"
git push
```

---

### Task 6: Add Run-Scoped Checkpoint Staging

**Files:**
- Create: `src/astock_lens/data/bootstrap_checkpoint.py`
- Create: `tests/unit/test_bootstrap_checkpoint.py`
- Modify: `src/astock_lens/data/bootstrap.py`

**Interfaces:**

```python
class BootstrapSymbolState(str, Enum):
    PENDING = "pending"
    SUCCESS = "success"
    EMPTY = "empty"
    TIMEOUT = "timeout"
    SOURCE_ERROR = "source_error"

class BootstrapManifestEntry(DomainRecord):
    symbol: str
    status: BootstrapSymbolState
    bars: int = 0
    attempts: int = 0
    last_error: str | None = None
    updated_at: datetime

class BootstrapManifest(DomainRecord):
    as_of: date
    required_valid_bars: int
    entries: tuple[BootstrapManifestEntry, ...]
```

Required paths:

```text
data/raw/bootstrap/<as-of>/manifest.json
data/raw/bootstrap/<as-of>/parts/*.csv
```

- [ ] **Step 1: Test durable success**

Checkpoint a success, recreate the checkpoint object, and prove the symbol remains SUCCESS.

- [ ] **Step 2: Test resume**

Given 100 symbols where 40 are SUCCESS, resume exposes only remaining 60 as work.

- [ ] **Step 3: Test idempotent repeated success**

Repeated successful checkpoint for the same symbol must not duplicate canonical rows after compaction.

- [ ] **Step 4: Implement atomic manifest writes**

Use temp file + atomic replace.

- [ ] **Step 5: Implement staged part writes**

Do not call `write_merged(daily_bars.csv, ...)` after every scheduler completion/chunk.

- [ ] **Step 6: Commit**

```bash
git add src/astock_lens/data/bootstrap_checkpoint.py \
        src/astock_lens/data/bootstrap.py \
        tests/unit/test_bootstrap_checkpoint.py
git commit -m "数据：为冷启动增加按标的持久化检查点"
git push
```

---

### Task 7: Implement Deterministic One-Time Compaction

**Files:**
- Modify: `src/astock_lens/data/bootstrap_checkpoint.py`
- Modify: `src/astock_lens/data/sync.py`
- Test: `tests/unit/test_bootstrap_checkpoint.py`

**Interfaces:**

```python
def compact_bootstrap_run(
    *,
    checkpoint: BootstrapCheckpoint,
    canonical_path: Path,
) -> tuple[int, int]:
    ...
```

- [ ] **Step 1: Test deterministic compaction**

Same staged parts in different filesystem enumeration order must produce byte-identical canonical CSV.

- [ ] **Step 2: Test idempotence**

Two compactions produce identical canonical content.

- [ ] **Step 3: Test key replacement**

Existing `(symbol, trade_date)` rows are replaced, not duplicated.

- [ ] **Step 4: Implement one-time compaction**

Read canonical once, read successful staged parts, deterministic merge, atomic canonical write.

- [ ] **Step 5: Commit**

```bash
git add src/astock_lens/data/bootstrap_checkpoint.py \
        src/astock_lens/data/sync.py \
        tests/unit/test_bootstrap_checkpoint.py
git commit -m "数据：冷启动完成后一次性确定性合并行情"
git push
```

---

### Task 8: Wire Batch-First + Fallback-Only-for-Gaps

**Files:**
- Modify: `src/astock_lens/data/bootstrap.py`
- Modify: `src/astock_lens/data/bootstrap_sources.py`
- Modify provider adapter chosen by Task 3, if any.
- Modify: `tests/unit/test_bootstrap_batch_fallback.py`

**Interfaces:**

```python
def bootstrap_liquidity_history(
    *,
    batch_source: BatchMarketBarSource | None,
    fallback_source: SymbolBarFallbackSource,
    ...
) -> BootstrapSyncResult:
    ...
```

- [ ] **Step 1: Test full batch coverage**

If batch source satisfies all 100 symbols, fallback request count must be 0.

- [ ] **Step 2: Test partial batch coverage**

If batch covers 83/100, fallback unique symbols must be exactly the missing 17.

- [ ] **Step 3: Test no batch source**

`batch_source=None` uses bounded fallback and still satisfies all safety properties.

- [ ] **Step 4: Implement chosen Task 3 adapter if evidence exists**

If Task 3 concluded `NO_BATCH_PRIMARY_AVAILABLE`, do not invent one.

- [ ] **Step 5: Test result equivalence**

Given identical synthetic bars, batch+fallback and fallback-only must produce identical final canonical content.

- [ ] **Step 6: Commit**

```bash
git add src/astock_lens/data/bootstrap.py \
        src/astock_lens/data/bootstrap_sources.py \
        tests/unit/test_bootstrap_batch_fallback.py \
        <provider-adapter-if-real>
git commit -m "数据：冷启动采用批量优先并仅对缺口逐标的补抓"
git push
```

---

### Task 9: Build Native Heartbeat and Progress Events

**Files:**
- Create: `src/astock_lens/data/bootstrap_progress.py`
- Create: `tests/unit/test_bootstrap_progress.py`
- Modify: `src/astock_lens/cli/app.py`
- Modify scheduler/checkpoint wiring.

**Interfaces:**

```python
class BootstrapProgress(DomainRecord):
    total: int
    processed: int
    satisfied: int
    failed: int
    pending: int
    inflight: int
    elapsed_seconds: float
    throughput_per_second: float

class ProgressSink(Protocol):
    def emit(self, progress: BootstrapProgress) -> None: ...
```

- [ ] **Step 1: Test heartbeat during a slow fake run**

A slow run must emit progress before completion.

- [ ] **Step 2: Test no hard-coded total/date**

Progress derives total/date from invocation.

- [ ] **Step 3: Implement CLI heartbeat**

Example:

```text
processed 820/5301 | satisfied 791 | failed 8 | pending 4482 | inflight 6 | 3.8 sym/s | elapsed 00:03:42
```

- [ ] **Step 4: Make external watcher dynamic or deprecate it**

Remove hard-coded TOTAL/REQUIRED/date values from `scripts/watch-bootstrap.sh` if it remains.

- [ ] **Step 5: Commit**

```bash
git add src/astock_lens/data/bootstrap_progress.py \
        src/astock_lens/cli/app.py \
        scripts/watch-bootstrap.sh \
        tests/unit/test_bootstrap_progress.py
git commit -m "可观测：给冷启动命令增加内建心跳与实时进度"
git push
```

---

### Task 10: Prove Scale Properties With a 5,300-Symbol Fake Source

**Files:**
- Create: `tests/stress/test_bootstrap_scale_properties.py`

**This is the hard gate before any new full-market live run.**

- [ ] **Step 1: All-success property**

With 5,300 fake symbols and sufficiently-wide first window:
- all satisfy;
- unique request count <= 5,300 without batch source;
- no satisfied symbol is requested twice;
- max active <= configured max-inflight;
- manifest ends terminal.

- [ ] **Step 2: Mixed failure property**

Inject deterministic:
- 1% timeout;
- 1% source error;
- 1% empty history.

Assert successes persist, failures remain explicit, run converges, and request count stays inside configured retry upper bound.

- [ ] **Step 3: Crash/resume property**

Abort after 2,000 successes, restart, assert first 2,000 are not requested again, and final compaction equals uninterrupted reference run.

- [ ] **Step 4: Batch partial-coverage property**

If batch source covers 90%, fallback calls must be <= the uncovered population plus explicit configured retries.

- [ ] **Step 5: Run stress suite**

```bash
uv run pytest tests/stress/test_bootstrap_scale_properties.py -v
```

- [ ] **Step 6: Full verification before live gate**

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
git diff --check
```

- [ ] **Step 7: Commit**

```bash
git add tests/stress/test_bootstrap_scale_properties.py
git commit -m "压力：用五千三百标的假源证明冷启动收敛与请求上界"
git push
```

## LIVE FULL-MARKET GATE

If Task 10 does not pass completely, STOP. The Agent is not authorized to run 5,000+ live symbols.

---

### Task 11: Execute the Real 100-Symbol Gate

**Files:**
- Modify: `docs/REVIEW_NOTES.md`

- [ ] **Step 1: Use the real CLI path**

Do not manually crop a CSV and invoke analysis only.

The command must execute the same `sync-bootstrap` orchestration intended for full market, with a deterministic 100-symbol operator/test subset mechanism.

If no subset flag exists, add one with benchmark/operator-only semantics, for example:

```text
astock sync-bootstrap --as-of ... --limit-symbols 100
```

It must not alter product Universe semantics.

- [ ] **Step 2: Record**

```text
symbols
batch requests
fallback requests
timeouts
source errors
satisfied
elapsed
throughput
peak active
resume test result
```

- [ ] **Step 3: Interrupt and resume once**

Prove completed symbols are skipped.

- [ ] **Step 4: Gate**

100-symbol gate passes only if progress is visible, there is no unexplained stall, request counts fit bounds, resume works, and canonical result is produced.

- [ ] **Step 5: Commit evidence**

```bash
git add docs/REVIEW_NOTES.md
git commit -m "验证：通过百标的真实冷启动路径门禁"
git push
```

---

### Task 12: Execute the Real 500-Symbol Gate

**Files:**
- Modify: `docs/REVIEW_NOTES.md`

- [ ] **Step 1: Run the same real command path at 500 symbols**

- [ ] **Step 2: Record Task 11 metrics plus**

```text
staging size
compaction duration
max RSS
active worker/process count before/during/after
remaining background worker count after command exits
```

- [ ] **Step 3: Verify no leaked execution**

After command completion, no orphaned bootstrap worker/process may continue remote work.

- [ ] **Step 4: Gate**

If any unexplained stall exceeds heartbeat interval, or work stays alive after terminal state, STOP.

- [ ] **Step 5: Commit**

```bash
git add docs/REVIEW_NOTES.md
git commit -m "验证：通过五百标的真实冷启动路径门禁"
git push
```

---

### Task 13: Full-Market Run — Only After Gates Pass

**Files:**
- Modify: `docs/REVIEW_NOTES.md`
- Modify: `docs/ROADMAP.md`
- Modify: `.workbuddy/memory/2026-09-18.md`

**Authorization condition:** Task 10 + Task 11 + Task 12 must all have explicit PASS evidence.

- [ ] **Step 1: Preflight**

```bash
git rev-parse HEAD
git status --short
uv run astock doctor
```

Worktree must be clean.

- [ ] **Step 2: Start full live bootstrap**

Use approved concurrency/rate settings only.

- [ ] **Step 3: Monitor native heartbeat**

No `ps/lsof` inference should be required to know whether the job progresses.

- [ ] **Step 4: If interrupted, resume**

Resume from manifest.

- [ ] **Step 5: Record final evidence**

```text
broad symbols
satisfied
short
timeout
source_error
batch calls
fallback calls
elapsed
throughput
compaction seconds
canonical rows
Research Universe count after avg_amount_20d
```

- [ ] **Step 6: Final verification**

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
git diff --check
```

- [ ] **Step 7: Commit**

```bash
git add docs/REVIEW_NOTES.md docs/ROADMAP.md .workbuddy/memory/2026-09-18.md
git commit -m "验证：完成全市场冷启动架构重构与实测"
git push
```

---

## Mandatory STOP GATES

The Agent must stop and report instead of continuing when any of these occurs:

1. Transport timeout cannot actually bound the underlying network call.
2. 5,300-symbol fake test does not converge.
3. Active workers exceed the configured bound.
4. Timed-out execution continues accumulating in the background.
5. 100-symbol live gate stalls or does not resume correctly.
6. 500-symbol live gate stalls or leaks workers.
7. Provider returns systemic rate-limit/source errors.
8. Batch-source probe cannot prove correctness of a candidate batch source.
9. Canonical compaction is non-deterministic or non-idempotent.

Full-market execution is forbidden after any failed gate.

---

## Required Agent Completion Report

```text
1. Task commit SHAs
2. Remote HEAD
3. Batch-source probe conclusion
4. Chosen batch primary, or NO_BATCH_PRIMARY_AVAILABLE
5. Actual transport-timeout mechanism
6. Proof that Future timeout is not used as the network-timeout claim
7. Scheduler max-inflight setting and observed maximum
8. 5,300 fake-source request counts
9. 5,300 fake-source convergence result
10. Crash/resume test evidence
11. 100-symbol live metrics
12. 100-symbol resume evidence
13. 500-symbol live metrics
14. Worker/process leak check
15. Whether full-market gate was authorized
16. If run: full-market metrics
17. Native heartbeat sample
18. Canonical compaction result
19. Research Universe count
20. Full pytest result
21. Ruff check result
22. Ruff format result
23. mypy result
24. git diff --check result
25. git status --short
26. Any STOP GATE triggered
27. Any plan deviation and exact reason
```

Do not report "complete" if a required command or gate was skipped.

---

## Self-Review

### Spec coverage

- Batch-first/fallback boundary: Tasks 2, 3, 8.
- Real transport timeout: Task 4.
- Bounded completion-order execution: Task 5.
- Durable checkpoint/resume: Task 6.
- One-time compaction: Task 7.
- Native heartbeat: Task 9.
- 5,300 fake scale proof: Task 10.
- Real command 100/500 gates: Tasks 11–12.
- Full-market authorization only after gates: Task 13.

### Root-cause protection

The plan adds the missing all-workers-hung test that the previous one-hung-worker test did not cover. It also prevents scheduler timeout from being mistaken for network cancellation.

### Product-scope protection

No Universe, Candidate, strategy, regime, signal, or qualification threshold changes are authorized.

### Placeholder scan

No implementation TODO/TBD placeholders are present. `NO_BATCH_PRIMARY_AVAILABLE` is an explicit evidence-based valid outcome.
