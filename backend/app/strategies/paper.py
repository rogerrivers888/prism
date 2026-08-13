"""The paper broker: the strategy machine trading £100k of nothing.

Signals are computed after the close from that day's data; the order then
waits in pending_paper_orders until the NEXT session's open exists in the
database, fills there with the same cost model the backtest used, and becomes
a PaperTradeExecuted event on the strategy's stream. The projection tables
(paper_trades, paper_positions) rebuild from those events; the daily equity
row is derived and recomputable.

Every strategy runs the same £100k so the leaderboard compares like with
like. Dividends are credited through adjusted prices, as in the backtest.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import Date, Numeric, Text, delete, func, select, text
from sqlalchemy.dialects.postgresql import JSONB, UUID, insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.events.store import Event, append
from app.strategies.engine import Holding, evaluate
from app.strategies.features import FeatureService
from app.strategies.registry import Strategy, catch_up as registry_catch_up
from app.strategies.rules import parse_rules
from app.strategies.simulator import STARTING_CAPITAL, CostModel

logger = logging.getLogger(__name__)

MAX_FILL_ATTEMPTS = 5


class PendingPaperOrder(Base):
    __tablename__ = "pending_paper_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    ticker: Mapped[str]
    side: Mapped[str]
    signal_date: Mapped[date] = mapped_column(Date)
    rule_fired: Mapped[str]
    metric_values: Mapped[dict] = mapped_column(JSONB)
    attempts: Mapped[int]


class PaperTrade(Base):
    __tablename__ = "paper_trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    ticker: Mapped[str]
    side: Mapped[str]
    quantity: Mapped[Decimal] = mapped_column(Numeric)
    price: Mapped[Decimal] = mapped_column(Numeric)
    currency: Mapped[str]
    spread_cost: Mapped[Decimal] = mapped_column(Numeric)
    commission: Mapped[Decimal] = mapped_column(Numeric)
    signal_date: Mapped[date] = mapped_column(Date)
    fill_date: Mapped[date] = mapped_column(Date)
    rule_fired: Mapped[str]
    metric_values: Mapped[dict] = mapped_column(JSONB)
    event_id: Mapped[int]


class PaperPosition(Base):
    __tablename__ = "paper_positions"

    strategy_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    ticker: Mapped[str] = mapped_column(Text, primary_key=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric)
    avg_cost: Mapped[Decimal] = mapped_column(Numeric)
    opened_at: Mapped[date] = mapped_column(Date)
    rule_fired: Mapped[str]
    metric_values: Mapped[dict] = mapped_column(JSONB)
    last_event_id: Mapped[int]


class PaperEquityDaily(Base):
    __tablename__ = "paper_equity_daily"

    strategy_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    equity: Mapped[Decimal] = mapped_column(Numeric)
    cash: Mapped[Decimal] = mapped_column(Numeric)


# ---------------------------------------------------------------- projection


async def apply_paper_event(session: AsyncSession, event: Event) -> None:
    """Fold one PaperTradeExecuted into the trade log and the position book."""
    if event.event_type != "PaperTradeExecuted":
        return
    payload = event.payload
    exists = (
        await session.execute(
            select(PaperTrade.id).where(PaperTrade.event_id == event.id)
        )
    ).scalar_one_or_none()
    if exists is not None:
        return  # idempotent replay

    session.add(PaperTrade(
        strategy_id=event.stream_id,
        ticker=payload["ticker"],
        side=payload["side"],
        quantity=Decimal(str(payload["quantity"])),
        price=Decimal(str(payload["price"])),
        currency=payload["currency"],
        spread_cost=Decimal(str(payload["spread_cost"])),
        commission=Decimal(str(payload["commission"])),
        signal_date=date.fromisoformat(payload["signal_date"]),
        fill_date=date.fromisoformat(payload["fill_date"]),
        rule_fired=payload["rule_fired"],
        metric_values=payload["metric_values"],
        event_id=event.id,
    ))

    position = await session.get(PaperPosition, (event.stream_id, payload["ticker"]))
    quantity = float(payload["quantity"])
    if payload["side"] == "buy":
        if position is None:
            session.add(PaperPosition(
                strategy_id=event.stream_id,
                ticker=payload["ticker"],
                quantity=Decimal(str(quantity)),
                avg_cost=Decimal(str(payload["price"])),
                opened_at=date.fromisoformat(payload["fill_date"]),
                rule_fired=payload["rule_fired"],
                metric_values=payload["metric_values"],
                last_event_id=event.id,
            ))
        else:
            old_quantity = float(position.quantity)
            total = old_quantity + quantity
            position.avg_cost = Decimal(str(
                (old_quantity * float(position.avg_cost) + quantity * float(payload["price"])) / total
            ))
            position.quantity = Decimal(str(total))
            position.last_event_id = event.id
    else:
        if position is not None:
            remaining = float(position.quantity) - quantity
            if remaining <= 1e-9:
                await session.delete(position)
            else:
                position.quantity = Decimal(str(remaining))
                position.last_event_id = event.id
    await session.flush()


# ---------------------------------------------------------------- the run


@dataclass
class PaperRunReport:
    strategies_evaluated: int = 0
    orders_signalled: int = 0
    orders_filled: int = 0
    orders_dropped: int = 0
    equity_rows: int = 0

    def as_dict(self) -> dict:
        return dict(self.__dict__)


async def cash_balance(session: AsyncSession, strategy_id: uuid.UUID) -> float:
    """Cash = starting capital + every fill folded in. Derived from the trade
    log so it cannot drift from the events."""
    rows = (
        await session.execute(
            select(PaperTrade).where(PaperTrade.strategy_id == strategy_id)
        )
    ).scalars()
    cash = STARTING_CAPITAL
    for trade in rows:
        gross = float(trade.quantity) * float(trade.price)
        friction = float(trade.spread_cost) + float(trade.commission)
        if trade.side == "buy":
            cash -= gross + friction
        else:
            cash += gross - friction
    return cash


async def run_paper_day(
    session: AsyncSession,
    service: FeatureService,
    today: date,
    costs: CostModel | None = None,
) -> PaperRunReport:
    """One nightly cycle: fill yesterday's pending orders at today's open,
    then signal new orders from today's close for tomorrow.

    Ordering matters: fills first, so a rebalance signalled yesterday is in
    the book before today's evaluation looks at holdings.
    """
    costs = costs or CostModel()
    report = PaperRunReport()

    active = list((
        await session.execute(select(Strategy).where(Strategy.status == "active"))
    ).scalars())

    # ---- 1. fill what was signalled -----------------------------------
    pending = list((
        await session.execute(select(PendingPaperOrder).order_by(PendingPaperOrder.id))
    ).scalars())
    for order in pending:
        fill = service.open_price(order.ticker, today)
        if fill is None:
            order.attempts += 1
            if order.attempts >= MAX_FILL_ATTEMPTS:
                logger.warning(
                    "dropping order %s %s for %s: no print in %d sessions",
                    order.side, order.ticker, order.strategy_id, order.attempts,
                )
                await session.delete(order)
                report.orders_dropped += 1
            continue

        security = service.securities.get(order.ticker)
        market_cap = order.metric_values.get("price:market_cap")
        spread_bps = costs.spread_bps(security.quote_currency if security else None, market_cap)

        if order.side == "buy":
            # Size at fill time on live cash: equal weight of what the
            # strategy's rules target, bounded by what is actually there.
            strategy = next((s for s in active if s.strategy_id == order.strategy_id), None)
            if strategy is None:
                await session.delete(order)
                report.orders_dropped += 1
                continue
            max_positions = parse_rules(strategy.rules).sizing.max_positions
            open_positions = (
                await session.execute(
                    select(func.count()).select_from(PaperPosition)
                    .where(PaperPosition.strategy_id == order.strategy_id)
                )
            ).scalar() or 0
            cash = await cash_balance(session, order.strategy_id)
            slots = max(max_positions - open_positions, 1)
            budget = cash / slots
            spread_cost = budget * spread_bps / 10_000
            investable = budget - spread_cost - costs.commission_per_order
            if investable < fill:
                logger.warning("insufficient paper cash for %s %s", order.ticker, order.strategy_id)
                await session.delete(order)
                report.orders_dropped += 1
                continue
            quantity = investable / fill
        else:
            position = await session.get(PaperPosition, (order.strategy_id, order.ticker))
            if position is None:
                await session.delete(order)
                report.orders_dropped += 1
                continue
            quantity = float(position.quantity)
            spread_cost = quantity * fill * spread_bps / 10_000

        event = await append(
            session,
            stream_id=order.strategy_id,
            stream_type="strategy",
            event_type="PaperTradeExecuted",
            payload={
                "ticker": order.ticker,
                "side": order.side,
                "quantity": str(round(quantity, 6)),
                "price": str(round(fill, 6)),
                "currency": "GBP",
                "spread_cost": str(round(spread_cost, 4)),
                "commission": str(costs.commission_per_order),
                "signal_date": order.signal_date.isoformat(),
                "fill_date": today.isoformat(),
                "rule_fired": order.rule_fired,
                "metric_values": order.metric_values,
            },
            occurred_at=datetime.now(timezone.utc),
            actor="strategy-engine",
        )
        await apply_paper_event(session, event)
        await session.delete(order)
        report.orders_filled += 1

    # ---- 2. signal from today's close ---------------------------------
    for strategy in active:
        rules = parse_rules(strategy.rules)
        grid = service.rebalance_dates(rules.rebalance.frequency)
        if today not in grid:
            continue
        report.strategies_evaluated += 1

        position_rows = (
            await session.execute(
                select(PaperPosition).where(PaperPosition.strategy_id == strategy.strategy_id)
            )
        ).scalars()
        holdings = {
            p.ticker: Holding(
                ticker=p.ticker, opened=p.opened_at, quantity=float(p.quantity),
                avg_cost=float(p.avg_cost), rule_fired=p.rule_fired,
                metric_values=p.metric_values,
            )
            for p in position_rows
        }
        decision = evaluate(service, rules, today, holdings)
        for order in decision.orders:
            await session.execute(
                pg_insert(PendingPaperOrder)
                .values(
                    strategy_id=strategy.strategy_id,
                    ticker=order.ticker,
                    side=order.side,
                    signal_date=today,
                    rule_fired=order.rule_fired,
                    metric_values=order.metric_values,
                )
                .on_conflict_do_nothing(constraint="uq_pending_order")
            )
            report.orders_signalled += 1

    # ---- 3. mark every active strategy's book -------------------------
    for strategy in active:
        positions = list((
            await session.execute(
                select(PaperPosition).where(PaperPosition.strategy_id == strategy.strategy_id)
            )
        ).scalars())
        cash = await cash_balance(session, strategy.strategy_id)
        equity = cash
        for position in positions:
            index = service._bar_index(position.ticker, today)
            if index >= 0:
                equity += float(position.quantity) * service.bars[position.ticker][index].adjusted_close
        await session.execute(
            pg_insert(PaperEquityDaily)
            .values(strategy_id=strategy.strategy_id, date=today,
                    equity=round(equity, 2), cash=round(cash, 2))
            .on_conflict_do_update(
                constraint="pk_paper_equity_daily",
                set_={"equity": round(equity, 2), "cash": round(cash, 2)},
            )
        )
        report.equity_rows += 1

    await session.flush()
    return report
