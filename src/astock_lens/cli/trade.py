"""Trade Gate 人工下单前命令入口。"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, cast

import typer
from pydantic import ValidationError

from astock_lens.data.snapshots.resolve import resolve_snapshot_store
from astock_lens.data.storage.paths import resolve_storage_paths
from astock_lens.domain.enums import TradeAction, TradeProfile
from astock_lens.trade_gate.audit.cli import (
    CliThesisAuditAdapter,
    TradeAuditNotConfigured,
)
from astock_lens.trade_gate.context import TradeContextBuilder
from astock_lens.trade_gate.engine import TradeGateEngine
from astock_lens.trade_gate.metrics import summarize_trade_discipline
from astock_lens.trade_gate.models import (
    ExecutionRecord,
    TradeIntent,
    TradeMarketOverlay,
    TradeReview,
    TradeRiskProposal,
)
from astock_lens.trade_gate.profiles import load_trade_gate_profiles
from astock_lens.trade_gate.resolve import resolve_trade_ledger
from astock_lens.trade_gate.service import TradeGateService
from astock_lens.trade_gate.store import TradeLedgerStore

trade_app = typer.Typer(no_args_is_help=True, help="交易准入与交易纪律记录。")


def _service(store: TradeLedgerStore | None = None) -> TradeGateService:
    paths = resolve_storage_paths()
    ledger = store or resolve_trade_ledger()
    snapshot = resolve_snapshot_store(paths.snapshot_root, database=paths.database)
    adapter = CliThesisAuditAdapter.from_environment()
    return TradeGateService(
        store=ledger,
        context_builder=TradeContextBuilder(snapshot),
        audit_adapter=adapter,
        engine=TradeGateEngine(load_trade_gate_profiles()),
    )


@trade_app.command("evaluate")
def evaluate(
    symbol: str,
    action: Annotated[TradeAction, typer.Option("--action")],
    profile: Annotated[TradeProfile, typer.Option("--profile")],
    thesis: Annotated[str, typer.Option("--thesis")],
    holding_days: Annotated[int, typer.Option("--holding-days")],
    account_nav: Annotated[float, typer.Option("--account-nav")],
    entry_price: Annotated[float, typer.Option("--entry-price")],
    stop_price: Annotated[float, typer.Option("--stop-price")],
    quantity: Annotated[int, typer.Option("--quantity")],
    invalidation: Annotated[str, typer.Option("--invalidation")],
    fomo: Annotated[int, typer.Option("--fomo")],
    catalyst: Annotated[str | None, typer.Option("--catalyst")] = None,
    target_price: Annotated[float | None, typer.Option("--target-price")] = None,
    overlay_path: Annotated[Path | None, typer.Option("--market-overlay")] = None,
    as_of: Annotated[str | None, typer.Option("--as-of")] = None,
) -> None:
    """评估一个明确的 ENTRY 或 ADD 意图；PASS 仅表示 eligible。"""
    try:
        overlay = (
            TradeMarketOverlay.model_validate_json(
                overlay_path.read_text(encoding="utf-8")
            )
            if overlay_path
            else None
        )
        intent = TradeIntent(
            id=f"intent-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}",
            symbol=symbol,
            action=action,
            profile=profile,
            thesis=thesis,
            catalyst=catalyst,
            expected_holding_days=holding_days,
            created_at=datetime.now(UTC),
            risk=TradeRiskProposal(
                account_nav=account_nav,
                planned_entry_price=entry_price,
                stop_loss_price=stop_price,
                target_price=target_price,
                quantity=quantity,
                invalidation_rule=invalidation,
            ),
        )
        moment = (
            datetime.fromisoformat(as_of).replace(tzinfo=UTC)
            if as_of
            else intent.created_at
        )
        service = _service()
        evaluation = service.create_and_evaluate(
            intent=intent, fomo_score=fomo, as_of=moment, overlay=overlay
        )
    except TradeAuditNotConfigured:
        typer.echo("decision: WAIT\nmissing:\n- AI_AUDIT_UNAVAILABLE")
        return
    except (OSError, ValueError, ValidationError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        f"Trade Gate\nsymbol: {symbol}\naction/profile: {action.value} / {profile.value}\nscore: {evaluation.weighted_score:.1f} / 100\ndecision: {evaluation.decision.value}\nevaluation_id: {evaluation.id}"
    )


@trade_app.command("show")
def show(evaluation_id: str) -> None:
    record = resolve_trade_ledger().read_evaluation(evaluation_id)
    if record is None:
        raise typer.BadParameter(f"unknown evaluation: {evaluation_id}")
    typer.echo(record.model_dump_json(indent=2))


@trade_app.command("override")
def override(
    evaluation_id: str,
    reason: Annotated[str, typer.Option("--reason")],
    evidence: Annotated[list[str], typer.Option("--evidence")],
    fomo: Annotated[int, typer.Option("--fomo")],
    position_limit_pct: Annotated[float, typer.Option("--position-limit-pct")],
    stop_rule: Annotated[str, typer.Option("--stop-rule")],
    ack_risk: Annotated[bool, typer.Option("--ack-risk")] = False,
) -> None:
    store = resolve_trade_ledger()
    service = TradeGateService(
        store=store,
        context_builder=cast(TradeContextBuilder, None),
        audit_adapter=cast(CliThesisAuditAdapter, None),
        engine=cast(TradeGateEngine, None),
    )
    try:
        result = service.override(
            evaluation_id,
            reason=reason,
            evidence=tuple(evidence),
            fomo_score=fomo,
            manual_position_limit_pct=position_limit_pct,
            manual_stop_rule=stop_rule,
            ack_risk=ack_risk,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(result.model_dump_json(indent=2))


@trade_app.command("execute")
def execute(
    evaluation_id: str,
    fill_price: Annotated[float, typer.Option("--fill-price")],
    quantity: Annotated[int, typer.Option("--quantity")],
    plan_id: Annotated[str | None, typer.Option("--plan-id")] = None,
    override_id: Annotated[str | None, typer.Option("--override-id")] = None,
) -> None:
    service = TradeGateService(
        store=resolve_trade_ledger(),
        context_builder=cast(TradeContextBuilder, None),
        audit_adapter=cast(CliThesisAuditAdapter, None),
        engine=cast(TradeGateEngine, None),
    )
    try:
        result = service.record_execution(
            evaluation_id=evaluation_id,
            fill_price=fill_price,
            quantity=quantity,
            filled_at=datetime.now(UTC),
            plan_id=plan_id,
            override_id=override_id,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(result.model_dump_json(indent=2))


@trade_app.command("review")
def review(path: Path) -> None:
    review = TradeReview.model_validate_json(path.read_text(encoding="utf-8"))
    resolve_trade_ledger().write_review(review)
    typer.echo(f"review recorded: {review.id}")


@trade_app.command("stats")
def stats() -> None:
    root = resolve_storage_paths().trade_root
    executions = tuple(
        ExecutionRecord.model_validate_json(p.read_text(encoding="utf-8"))
        for p in sorted((root / "executions").glob("*.json"))
    )
    reviews = tuple(
        TradeReview.model_validate_json(p.read_text(encoding="utf-8"))
        for p in sorted((root / "reviews").glob("*.json"))
    )
    typer.echo(
        summarize_trade_discipline(executions, reviews).model_dump_json(indent=2)
    )
