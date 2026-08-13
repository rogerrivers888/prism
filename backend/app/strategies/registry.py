"""The strategy registry: pre-registered, immutable, event-sourced.

A strategy is registered before any backtest runs. Its stream then accumulates
lifecycle events — activated, paused, promoted, retired — and its paper
trades. Nothing is ever edited: a tweak is a NEW strategy with
parent_strategy_id set, and the whole family counts as multiple trials when
results are deflated.

The strategies table is a projection over those streams, rebuildable from
event 1 like every other read model here.
"""

import logging
import statistics
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import BigInteger, Date, DateTime, Numeric, Text, func, select, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.events.store import Event, append, read_all
from app.projections.positions import ProjectionState
from app.strategies.rules import parse_rules, rule_signature

logger = logging.getLogger(__name__)

PROJECTION_NAME = "strategies"

# McLean & Pontiff (2016): anomaly returns fall roughly in half after the
# paper publishing them appears. Every strategy card carries this.
DEFAULT_DECAY_NOTE = (
    "Published anomalies have historically delivered roughly half their "
    "in-sample returns after publication (McLean & Pontiff 2016). Expect "
    "less than the source reports, and treat the backtest as a ceiling."
)

# Return-stream correlation above this flags the newcomer as a duplicate of a
# named sibling and blocks activation until overridden.
DUPLICATE_CORRELATION = 0.8


class Strategy(Base):
    __tablename__ = "strategies"

    strategy_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    name: Mapped[str]
    hypothesis: Mapped[str]
    authority: Mapped[str]
    citation: Mapped[str | None]
    rules: Mapped[dict] = mapped_column(JSONB)
    rule_signature: Mapped[str]
    horizon: Mapped[str]
    expected_trade_frequency: Mapped[str]
    expected_holding_period: Mapped[str]
    predicted_performance: Mapped[str]
    parent_strategy_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    decay_note: Mapped[str]
    encoding_deviations: Mapped[str | None]
    status: Mapped[str]
    stage: Mapped[str]
    duplicate_of: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    duplicate_correlation: Mapped[float | None] = mapped_column(Numeric)
    duplicate_override_note: Mapped[str | None]
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_event_id: Mapped[int] = mapped_column(BigInteger)


class StrategyBacktest(Base):
    __tablename__ = "strategy_backtests"

    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    results: Mapped[dict] = mapped_column(JSONB)
    monthly_returns: Mapped[list] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DuplicateStrategyError(Exception):
    """Raised when the rule signature already exists — the same strategy
    under a different name is not a new strategy."""


async def register(
    session: AsyncSession,
    *,
    name: str,
    hypothesis: str,
    authority: str,
    rules: dict,
    horizon: str,
    expected_trade_frequency: str,
    expected_holding_period: str,
    predicted_performance: str,
    citation: str | None = None,
    parent_strategy_id: uuid.UUID | None = None,
    encoding_deviations: str | None = None,
    decay_note: str = DEFAULT_DECAY_NOTE,
    actor: str = "roger",
) -> uuid.UUID:
    """Write the registration event. Validates rules, rejects signature
    duplicates outright. The backtest has not run yet — that is the point."""
    parse_rules(rules)
    signature = rule_signature(rules)

    existing = (
        await session.execute(
            select(Strategy).where(Strategy.rule_signature == signature)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise DuplicateStrategyError(
            f"identical rules already registered as '{existing.name}' "
            f"({existing.strategy_id})"
        )

    strategy_id = uuid.uuid4()
    await append(
        session,
        stream_id=strategy_id,
        stream_type="strategy",
        event_type="StrategyRegistered",
        payload={
            "name": name,
            "hypothesis": hypothesis,
            "authority": authority,
            "citation": citation,
            "rules": rules,
            "horizon": horizon,
            "expected_trade_frequency": expected_trade_frequency,
            "expected_holding_period": expected_holding_period,
            "predicted_performance": predicted_performance,
            "parent_strategy_id": str(parent_strategy_id) if parent_strategy_id else None,
            "decay_note": decay_note,
            "encoding_deviations": encoding_deviations,
        },
        occurred_at=datetime.now(timezone.utc),
        actor=actor,
    )
    await catch_up(session)
    return strategy_id


class ActivationBlocked(Exception):
    pass


async def activate(
    session: AsyncSession,
    strategy_id: uuid.UUID,
    override_note: str | None = None,
    actor: str = "roger",
) -> None:
    """Activate for paper trading. Blocked while flagged as a duplicate,
    unless the override is stated in writing — and then recorded forever."""
    strategy = await session.get(Strategy, strategy_id)
    if strategy is None:
        raise ValueError(f"unknown strategy {strategy_id}")
    if strategy.duplicate_of is not None and not override_note:
        raise ActivationBlocked(
            f"flagged as a duplicate of {strategy.duplicate_of} "
            f"(return correlation {strategy.duplicate_correlation}); "
            "activation needs an explicit override note"
        )
    await append(
        session,
        stream_id=strategy_id,
        stream_type="strategy",
        event_type="StrategyActivated",
        payload={"duplicate_override_note": override_note},
        occurred_at=datetime.now(timezone.utc),
        actor=actor,
    )
    await catch_up(session)


async def _lifecycle(session, strategy_id, event_type, payload, actor):
    if await session.get(Strategy, strategy_id) is None:
        raise ValueError(f"unknown strategy {strategy_id}")
    await append(
        session,
        stream_id=strategy_id,
        stream_type="strategy",
        event_type=event_type,
        payload=payload,
        occurred_at=datetime.now(timezone.utc),
        actor=actor,
    )
    await catch_up(session)


async def pause(session, strategy_id, reason: str, actor: str = "roger"):
    await _lifecycle(session, strategy_id, "StrategyPaused", {"reason": reason}, actor)


async def retire(session, strategy_id, reason: str, actor: str = "roger"):
    await _lifecycle(session, strategy_id, "StrategyRetired", {"reason": reason}, actor)


async def promote(session, strategy_id, stage: str, note: str | None = None, actor: str = "roger"):
    """backtest -> paper -> proven. Only ever called from an explicit human
    action; nothing in the engine promotes automatically."""
    await _lifecycle(session, strategy_id, "StrategyPromoted", {"stage": stage, "note": note}, actor)


# ---------------------------------------------------------------- projection


async def apply(session: AsyncSession, event: Event) -> None:
    if event.stream_type != "strategy":
        return
    payload = event.payload
    event_type = event.event_type

    if event_type == "StrategyRegistered":
        session.add(
            Strategy(
                strategy_id=event.stream_id,
                name=payload["name"],
                hypothesis=payload["hypothesis"],
                authority=payload["authority"],
                citation=payload.get("citation"),
                rules=payload["rules"],
                rule_signature=rule_signature(payload["rules"]),
                horizon=payload["horizon"],
                expected_trade_frequency=payload["expected_trade_frequency"],
                expected_holding_period=payload["expected_holding_period"],
                predicted_performance=payload["predicted_performance"],
                parent_strategy_id=(
                    uuid.UUID(payload["parent_strategy_id"])
                    if payload.get("parent_strategy_id")
                    else None
                ),
                decay_note=payload["decay_note"],
                encoding_deviations=payload.get("encoding_deviations"),
                status="registered",
                stage="backtest",
                registered_at=event.occurred_at,
                last_event_id=event.id,
            )
        )
        return

    strategy = await session.get(Strategy, event.stream_id)
    if strategy is None:
        logger.warning("lifecycle event for unknown strategy %s", event.stream_id)
        return

    if event_type == "StrategyActivated":
        strategy.status = "active"
        if payload.get("duplicate_override_note"):
            strategy.duplicate_override_note = payload["duplicate_override_note"]
    elif event_type == "StrategyPaused":
        strategy.status = "paused"
    elif event_type == "StrategyRetired":
        strategy.status = "retired"
    elif event_type == "StrategyPromoted":
        strategy.stage = payload["stage"]
    # PaperTradeExecuted is handled by the paper-book projection.
    strategy.last_event_id = event.id


_BATCH = 500


async def _get_state(session: AsyncSession) -> ProjectionState:
    state = await session.get(ProjectionState, PROJECTION_NAME)
    if state is None:
        state = ProjectionState(name=PROJECTION_NAME, last_event_id=0)
        session.add(state)
        await session.flush()
    return state


async def catch_up(session: AsyncSession) -> int:
    state = await _get_state(session)
    processed = 0
    while True:
        batch = await read_all(session, after_id=state.last_event_id, limit=_BATCH)
        for event in batch:
            await apply(session, event)
            state.last_event_id = event.id
            processed += 1
        if len(batch) < _BATCH:
            break
    if processed:
        state.updated_at = func.now()
    await session.flush()
    return processed


async def rebuild(session: AsyncSession) -> int:
    await session.execute(text("TRUNCATE strategies"))
    state = await _get_state(session)
    state.last_event_id = 0
    await session.flush()
    session.expire_all()
    return await catch_up(session)


# ---------------------------------------------------------------- novelty


def correlation(a: dict[str, float], b: dict[str, float]) -> float | None:
    """Pearson correlation over the months both strategies have returns for.

    Fewer than 24 shared months is refused: correlation on a dozen points is
    a coin toss dressed as a statistic.
    """
    shared = sorted(set(a) & set(b))
    if len(shared) < 24:
        return None
    xs = [a[m] for m in shared]
    ys = [b[m] for m in shared]
    try:
        return statistics.correlation(xs, ys)
    except statistics.StatisticsError:
        # One side has zero variance - a flat return stream correlates with
        # nothing.
        return None


async def check_novelty(
    session: AsyncSession, strategy_id: uuid.UUID, monthly_returns: list[dict]
) -> None:
    """Correlate this strategy's backtest returns against every sibling's.

    Runs after the gate backtest (there is nothing to correlate before). Above
    the threshold, the strategy is marked duplicate-of-named-sibling and
    activation is blocked until overridden in writing.
    """
    mine = {row["month"]: row["return_pct"] for row in monthly_returns}
    strategy = await session.get(Strategy, strategy_id)

    worst: tuple[uuid.UUID, float] | None = None
    others = (
        await session.execute(
            select(StrategyBacktest)
            .where(StrategyBacktest.strategy_id != strategy_id)
            .order_by(StrategyBacktest.id.desc())
        )
    ).scalars()
    seen: set[uuid.UUID] = set()
    for other in others:
        # Latest backtest per sibling only.
        if other.strategy_id in seen:
            continue
        seen.add(other.strategy_id)
        theirs = {row["month"]: row["return_pct"] for row in other.monthly_returns}
        rho = correlation(mine, theirs)
        if rho is not None and (worst is None or rho > worst[1]):
            worst = (other.strategy_id, rho)

    if worst and worst[1] > DUPLICATE_CORRELATION:
        strategy.duplicate_of = worst[0]
        strategy.duplicate_correlation = round(worst[1], 4)
        logger.warning(
            "strategy %s flagged duplicate of %s (rho=%.3f)",
            strategy_id, worst[0], worst[1],
        )
    await session.flush()
