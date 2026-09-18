# Full-Market Bootstrap Architecture Redesign

**Date:** 2026-09-18  
**Status:** Approved by owner  
**Context:** `docs/RETROSPECTIVE-2026-09-18-full-market-bootstrap.md`

## 1. Purpose

Redesign the full-market bootstrap path so it is reliable, bounded, observable, resumable, and no longer structurally dependent on thousands of fragile per-symbol requests as the only path.

The immediate use case is still the same:

```text
Broad A-share listing
→ obtain enough recent bars to compute avg_amount_20d
→ build Research Universe
→ enrich only the Research Universe
```

The redesign must preserve all existing Research Universe semantics. It changes data-acquisition and execution reliability, not product thresholds.

## 2. Problem Statement

The current implementation exposed four implementation defects and one deeper architectural weakness:

1. repeated full-file scans created O(symbols × rows) CPU cost;
2. required trading bars were initially translated incorrectly into calendar days;
3. requested-window coverage was incorrectly used as a completion predicate;
4. `Future.result(timeout=...)` was treated as if it were a real network timeout;
5. the whole-market cold-start path still fundamentally depends on ~5,000+ per-symbol remote calls.

The fourth problem is still not fully solved in current code:

```python
for symbol in chunk:
    future.result(timeout=60)
```

The timeout is applied sequentially at result-consumption time. It is not a common absolute deadline from submission time, and it does not terminate the underlying network request.

Therefore:

```text
Future timeout != transport timeout
```

This distinction is load-bearing.

## 3. Approved Architecture

### 3.1 Two-source bootstrap boundary

Introduce a bootstrap-specific data-source abstraction:

```text
BootstrapBarSource
    ├── BatchMarketBarSource      preferred
    └── SymbolBarFallbackSource  gap filling / fallback
```

The system first probes whether currently available providers expose a real batch/full-market recent-history capability.

Preferred provider search order:

1. existing AkShare capability;
2. existing WeStock capability;
3. another provider already present in this repository;
4. otherwise no new provider is invented.

If no reliable batch capability exists, the system keeps the fallback path but still completes all reliability changes in this spec.

### 3.2 Batch-first semantics

If a batch source exists:

```text
batch fetch recent history
→ measure per-symbol valid-bar coverage
→ mark satisfied symbols
→ send only missing/failed symbols to fallback
```

Fallback must never refetch already satisfied symbols.

### 3.3 Real network timeout

Timeout responsibility belongs at the transport boundary.

The provider must expose actual bounded network I/O semantics:

```text
connect timeout
read timeout
```

A scheduler-level Future timeout may exist as defense-in-depth, but it must not be described or tested as the mechanism that stops a network call.

If the current AkShare transport does not expose a controllable real network timeout, the implementation must explicitly document that limitation and either:

- introduce a transport implementation where timeout can be controlled; or
- downgrade that provider to a best-effort fallback whose process isolation is required.

The Agent may not claim "single-symbol request is bounded to N seconds" unless the underlying I/O is actually bounded.

### 3.4 Bounded in-flight scheduler

Remove submit-all-and-wait-in-symbol-order behavior.

Required scheduler semantics:

```text
max_inflight = configured worker count

while work remains:
    maintain at most max_inflight active operations
    consume whichever finishes first
    checkpoint completed result
    submit next pending symbol
```

Each operation carries an absolute deadline measured from submission/start.

The total number of active remote operations must remain bounded.

### 3.5 Checkpoint staging

Do not repeatedly merge each chunk into the full `daily_bars.csv`.

Use run-scoped staging:

```text
data/raw/bootstrap/<as-of>/
    manifest.json
    parts/
        part-000001.csv
        part-000002.csv
        ...
```

Manifest state per symbol:

```text
symbol
status: pending | success | empty | timeout | source_error
bars
attempts
last_error
updated_at
```

A successful symbol is durably checkpointed before the scheduler forgets it.

After the run reaches a terminal state, compact staging into the canonical bar landing once.

Rerunning the same bootstrap resumes from manifest + landed evidence.

### 3.6 Heartbeat is part of the command

`sync-bootstrap` itself must emit progress.

At least every 10–20 seconds:

```text
processed X / total
satisfied
failed
pending
inflight
throughput
elapsed
```

ETA is optional and may only use throughput measured by the current command/path.

The existing shell watcher may remain as an operator convenience but is not the primary observability mechanism.

### 3.7 Scale gates

No code change in this redesign may be validated first with the full market.

Mandatory sequence:

```text
pure fake-source property tests
→ 100-symbol real sync-bootstrap
→ 500-symbol real sync-bootstrap
→ full broad-market bootstrap
```

The 100- and 500-symbol gates must execute the real `sync-bootstrap` code path.

A manually cropped analysis-only dataset does not count.

## 4. Mandatory Properties

The completed system must prove:

1. If all workers hang, chunk/run control flow still reaches a bounded scheduler verdict.
2. Running requests do not grow without bound after timeout.
3. Already-satisfied symbols are not requested again.
4. A normal symbol receives at most one request in the first sufficiently-wide round.
5. A run interrupted after checkpoint N resumes after N rather than from zero.
6. Number of remote requests has an explicit upper bound under a fake provider.
7. Missing rows are never fabricated.
8. Batch-source partial coverage falls back only for uncovered symbols.
9. A failed fallback symbol cannot discard successful neighbors.
10. The final canonical merge is deterministic and idempotent.
11. Heartbeat progresses on the same execution path being benchmarked.
12. The full-market gate cannot be started unless the 100/500 gates are recorded as passed.

## 5. Non-Goals

This redesign does not:

- change `avg_amount_20d >= 20,000,000`;
- change `min_listing_days = 120`;
- force the Research Universe to exactly 2,500 symbols;
- approve any Candidate Qualification absolute threshold;
- implement Market Regime / Market Validation / Signal;
- add a new paid/external provider without owner approval;
- optimize strategy/factor semantics;
- enable production Candidate publishing.

## 6. Stop Conditions

The Agent must stop and return evidence if:

- no controllable real transport timeout can be implemented for the active fallback source;
- no batch source exists and fallback stress tests cannot demonstrate bounded behavior;
- 100-symbol real command does not converge;
- 500-symbol real command shows request leakage, unbounded workers, non-resumable behavior, or unexplained stalls;
- the source starts returning systemic errors/rate limits.

The Agent is not authorized to "just try the full market anyway."

## 7. Acceptance Criteria

The redesign is accepted only when:

- batch capability probe evidence is committed;
- timeout semantics are correctly separated between transport and scheduler;
- scheduler uses bounded in-flight work and completion-order handling;
- staging manifest/checkpoint exists;
- canonical merge happens once per completed run or controlled compaction;
- 5,300-symbol fake-source test proves convergence/request bounds;
- 100-symbol and 500-symbol real `sync-bootstrap` runs pass;
- full-market run is only attempted after those gates;
- all repository tests, Ruff, formatting, mypy, and `git diff --check` pass.
