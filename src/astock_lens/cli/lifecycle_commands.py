"""Watchlist 与 Research 生命周期命令。"""

from datetime import UTC, datetime
from typing import Annotated

import typer
from pydantic import ValidationError

from astock_lens.domain.enums import WatchlistState
from astock_lens.research.adapters.cli import (
    CliDeepResearchAdapter,
    DeepResearchInvocationError,
    DeepResearchNotConfigured,
    resolve_adapter,
)
from astock_lens.research.models import ResearchRequest
from astock_lens.watchlist.models import WatchlistEntry
from astock_lens.watchlist.state_machine import (
    WatchlistTransitionError,
    open_entry,
    transition,
)

from . import runtime as rt


def _watchlist_state(value: str) -> WatchlistState:
    try:
        return WatchlistState(value.upper())
    except ValueError as error:
        known = ", ".join(item.value for item in WatchlistState)
        raise typer.BadParameter(
            f"{value!r} is not a watchlist state; known states are {known}"
        ) from error


def _edited(
    entry: WatchlistEntry,
    now: datetime,
    thesis: str | None,
    key_question: list[str] | None,
    risk_condition: list[str] | None,
    waiting_for: list[str] | None,
) -> WatchlistEntry:
    updates: dict[str, object] = {}
    if thesis is not None:
        updates["thesis"] = thesis
    if key_question:
        updates["key_questions"] = tuple(key_question)
    if risk_condition:
        updates["risk_conditions"] = tuple(risk_condition)
    if waiting_for:
        updates["waiting_for"] = tuple(waiting_for)
    return (
        entry if not updates else entry.model_copy(update=updates | {"updated_at": now})
    )


def _echo_entry(entry: WatchlistEntry) -> None:
    typer.echo(f"  watchlist: {entry.state} (since {entry.updated_at.isoformat()})")
    if entry.thesis is not None:
        typer.echo(f"    thesis: {entry.thesis}")
    for question in entry.key_questions:
        typer.echo(f"    key question: {question}")
    for risk in entry.risk_conditions:
        typer.echo(f"    risk: {risk}")
    for waiting in entry.waiting_for:
        typer.echo(f"    waiting for: {waiting}")
    for event in entry.timeline:
        origin = event.from_state.value if event.from_state else "new"
        detail = f" ({event.note})" if event.note else ""
        typer.echo(
            f"    timeline: {event.at.isoformat()} {origin} -> {event.to_state}{detail}"
        )


def watch(
    symbol: Annotated[
        str | None, typer.Argument(help="Symbol to track; omit to list the watchlist.")
    ] = None,
    thesis: Annotated[str | None, typer.Option("--thesis")] = None,
    key_question: Annotated[list[str] | None, typer.Option("--key-question")] = None,
    risk_condition: Annotated[
        list[str] | None, typer.Option("--risk-condition")
    ] = None,
    waiting_for: Annotated[list[str] | None, typer.Option("--waiting-for")] = None,
    state: Annotated[
        str | None, typer.Option("--state", help="Move the entry to this state.")
    ] = None,
    note: Annotated[str | None, typer.Option("--note")] = None,
) -> None:
    """Track a symbol, or list what is already tracked.

    A new entry starts at `DISCOVERED`. `--state` moves it along the path the
    design confirms — `DISCOVERED → WATCH → DEEP_RESEARCH → TRACK_SIGNAL` — and
    refuses anything else, including the states V1 must not reach.
    """
    store = rt._watchlist_store()
    if symbol is None:
        symbols = store.symbols()
        if not symbols:
            typer.echo("watchlist: empty")
            return
        for tracked in symbols:
            entry = store.read(tracked)
            if entry is not None:
                typer.echo(
                    f"{entry.symbol} {entry.state} updated {entry.updated_at.isoformat()}"
                )
        return
    now = datetime.now(UTC)
    entry = store.read(symbol)
    if entry is None:
        entry = open_entry(
            symbol,
            at=now,
            thesis=thesis,
            key_questions=key_question or (),
            risk_conditions=risk_condition or (),
            waiting_for=waiting_for or (),
        )
    else:
        entry = _edited(entry, now, thesis, key_question, risk_condition, waiting_for)
    if state is not None:
        try:
            entry = transition(entry, _watchlist_state(state), at=now, note=note)
        except WatchlistTransitionError as error:
            typer.echo(str(error), err=True)
            raise typer.Exit(code=1) from error
    store.write(entry)
    typer.echo(f"{entry.symbol} {entry.state}")
    _echo_entry(entry)


def _research_action(
    adapter: CliDeepResearchAdapter,
    *,
    symbol: str | None,
    status: str | None,
    result: str | None,
    thesis: str | None,
) -> None:
    if status is not None:
        observed = adapter.status(status)
        typer.echo(
            f"{observed.job_id} {observed.state} (terminal: {observed.is_terminal}) observed {observed.observed_at.isoformat()}"
        )
        if observed.message is not None:
            typer.echo(f"  {observed.message}")
        return
    if result is not None:
        summary = adapter.result(result)
        typer.echo(
            f"{summary.job_id} {summary.symbol} completed {summary.completed_at.isoformat()}"
        )
        typer.echo(f"  summary: {summary.summary}")
        typer.echo(f"  artifact: {summary.artifact_reference}")
        return
    if symbol is None:
        typer.echo(
            "research needs a symbol to submit, or --status/--result with a job id",
            err=True,
        )
        raise typer.Exit(code=1)
    entry = rt._watchlist_store().read(symbol)
    job = adapter.submit(
        ResearchRequest(
            symbol=symbol,
            as_of=datetime.now(UTC),
            thesis=thesis if thesis is not None else (entry.thesis if entry else None),
            key_questions=entry.key_questions if entry else (),
            risk_conditions=entry.risk_conditions if entry else (),
            waiting_for=entry.waiting_for if entry else (),
        )
    )
    typer.echo(
        f"{job.job_id} submitted for {job.symbol} at {job.submitted_at.isoformat()}"
    )


def research(
    symbol: Annotated[
        str | None, typer.Argument(help="Symbol to research, or a job id below.")
    ] = None,
    status: Annotated[
        str | None, typer.Option("--status", help="Poll this job instead.")
    ] = None,
    result: Annotated[
        str | None, typer.Option("--result", help="Read this job's summary instead.")
    ] = None,
    thesis: Annotated[
        str | None, typer.Option("--thesis", help="Override the watchlist thesis.")
    ] = None,
) -> None:
    """Hand a research request to the deep research adapter.

    The request is built from the watchlist entry's own reasoning, so the
    other system receives the questions this one was tracking. No adapter is
    configured by default: without `ASTOCK_DEEP_RESEARCH_CMD` there is nothing
    to submit to, and nothing is invented in its place.
    """
    try:
        adapter = resolve_adapter()
    except DeepResearchNotConfigured as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error
    try:
        _research_action(
            adapter, symbol=symbol, status=status, result=result, thesis=thesis
        )
    except (DeepResearchInvocationError, ValidationError) as error:
        typer.echo(f"deep research adapter failed: {error}", err=True)
        raise typer.Exit(code=1) from error


def register_watch(app: typer.Typer) -> None:
    app.command()(watch)


def register_research(app: typer.Typer) -> None:
    app.command()(research)


def register(app: typer.Typer) -> None:
    register_watch(app)
    register_research(app)
