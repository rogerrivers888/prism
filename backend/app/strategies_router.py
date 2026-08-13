"""Strategy machine endpoints: the leaderboard, the drill-down, today's trades.

Ranking is always on full-history expectancy, never on recent performance. A
board sorted by the last thirty days is a machine for promoting whatever just
got lucky, which is the specific failure this whole system is built to avoid.
"""

import uuid
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.fundamentals import PriceDaily, Security
from app.strategies import registry
from app.strategies.gate import expected_max_under_null, track_record_verdict
from app.strategies.paper import PaperEquityDaily, PaperPosition, PaperTrade
from app.strategies.rules import describe, parse_rules
from app.strategies.simulator import STARTING_CAPITAL, max_drawdown_pct

router = APIRouter(prefix="/strategies", tags=["strategies"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


class LeaderboardRow(BaseModel):
    strategy_id: str
    name: str
    authority: str
    citation: str | None
    horizon: str
    status: str
    stage: str
    registered_at: date
    started: date | None
    trades: int
    total_return_pct: float | None
    expectancy_r: float | None
    mean_trade_return_pct: float | None
    max_drawdown_pct: float | None
    cost_drag_pct: float | None
    # The sample-size sentence. Most rows will say "meaningless" for years.
    track_record_verdict: str
    # Backtest figures alongside, and what deflation does to them.
    backtest_mean_trade_pct: float | None
    backtest_excess_over_drift_pct: float | None
    deflated_survives: bool | None
    family_size: int | None
    duplicate_of: str | None
    decay_note: str


async def _paper_stats(session: AsyncSession, strategy_id: uuid.UUID) -> dict:
    """Realised paper performance, from the trade log and the equity curve."""
    trades = list((
        await session.execute(
            select(PaperTrade).where(PaperTrade.strategy_id == strategy_id)
            .order_by(PaperTrade.fill_date)
        )
    ).scalars())
    curve = list((
        await session.execute(
            select(PaperEquityDaily.date, PaperEquityDaily.equity)
            .where(PaperEquityDaily.strategy_id == strategy_id)
            .order_by(PaperEquityDaily.date)
        )
    ).all())

    out: dict = {
        "trades": len(trades),
        "started": trades[0].fill_date if trades else None,
        "total_return_pct": None,
        "max_drawdown_pct": None,
        "cost_drag_pct": None,
        "months": 0,
        "monthly_returns": [],
    }
    if curve:
        equity = [(d, float(e)) for d, e in curve]
        out["total_return_pct"] = round((equity[-1][1] / STARTING_CAPITAL - 1) * 100, 2)
        out["max_drawdown_pct"] = max_drawdown_pct(equity)
        by_month: dict[str, float] = {}
        for day, value in equity:
            by_month[f"{day.year:04d}-{day.month:02d}"] = value
        months = sorted(by_month)
        out["months"] = len(months)
        out["monthly_returns"] = [
            round((by_month[b] / by_month[a] - 1) * 100, 4)
            for a, b in zip(months, months[1:]) if by_month[a] > 0
        ]
    if trades:
        friction = sum(float(t.spread_cost) + float(t.commission) for t in trades)
        out["cost_drag_pct"] = round(friction / STARTING_CAPITAL * 100, 3)
    return out


async def _latest_backtest(session: AsyncSession, strategy_id: uuid.UUID):
    return (
        await session.execute(
            select(registry.StrategyBacktest)
            .where(registry.StrategyBacktest.strategy_id == strategy_id)
            .order_by(desc(registry.StrategyBacktest.id))
            .limit(1)
        )
    ).scalar_one_or_none()


@router.get("")
async def leaderboard(session: SessionDep) -> dict:
    """Boards split by horizon, each ranked on full-history expectancy.

    Short-term and long-term strategies are not comparable: a weekly momentum
    book and a quarterly value screen have different trade counts, different
    cost drags and different meanings of 'a good month'. Ranking them in one
    table would just sort by horizon.
    """
    strategies = list((
        await session.execute(select(registry.Strategy).order_by(registry.Strategy.name))
    ).scalars())

    boards: dict[str, list[LeaderboardRow]] = {"short": [], "medium": [], "long": []}
    for strategy in strategies:
        paper = await _paper_stats(session, strategy.strategy_id)
        backtest = await _latest_backtest(session, strategy.strategy_id)
        results = backtest.results if backtest else {}
        overall = results.get("overall", {})
        deflation = results.get("deflation", {})

        verdict = track_record_verdict(
            paper["months"], paper["trades"], paper["monthly_returns"]
        )
        boards.setdefault(strategy.horizon, []).append(LeaderboardRow(
            strategy_id=str(strategy.strategy_id),
            name=strategy.name,
            authority=strategy.authority,
            citation=strategy.citation,
            horizon=strategy.horizon,
            status=strategy.status,
            stage=strategy.stage,
            registered_at=strategy.registered_at.date(),
            started=paper["started"],
            trades=paper["trades"],
            total_return_pct=paper["total_return_pct"],
            expectancy_r=overall.get("expectancy_r"),
            mean_trade_return_pct=overall.get("mean_trade_return_pct"),
            max_drawdown_pct=paper["max_drawdown_pct"],
            cost_drag_pct=paper["cost_drag_pct"],
            track_record_verdict=verdict,
            backtest_mean_trade_pct=overall.get("mean_trade_return_pct"),
            backtest_excess_over_drift_pct=results.get("excess_over_drift_pct"),
            deflated_survives=(deflation.get("per_trade") or {}).get("survives"),
            family_size=(results.get("family") or {}).get("size"),
            duplicate_of=str(strategy.duplicate_of) if strategy.duplicate_of else None,
            decay_note=strategy.decay_note,
        ))

    # Rank on backtest expectancy where there is no paper history yet, and
    # never on anything recent.
    for rows in boards.values():
        rows.sort(key=lambda r: (r.mean_trade_return_pct is None,
                                 -(r.mean_trade_return_pct or 0)))

    # Cohort deflation, separate from the per-family kind. Lineage deflation
    # asks "how many variants of THIS idea were tried"; every strategy here is
    # its own root, so that number is one. But twelve strategies were run
    # against the same fifteen years at the same time, and the best of twelve
    # is a different question from the best of one. Showing only the lineage
    # bar would understate how much searching actually happened.
    tested = [r for rows in boards.values() for r in rows
              if r.mean_trade_return_pct is not None]
    cohort = None
    if len(tested) > 1:
        best = max(tested, key=lambda r: r.mean_trade_return_pct)
        z = expected_max_under_null(len(tested))
        cohort = {
            "strategies_tested": len(tested),
            "expected_max_z": round(z, 3),
            "best": best.name,
            "note": (
                f"{len(tested)} strategies were tested against the same history. "
                f"Even if all {len(tested)} were worthless, the best would be "
                f"expected to clear roughly {z:.1f} standard errors on luck alone. "
                "Read the top row as the winner of a competition, not as a discovery."
            ),
        }

    return {
        "boards": boards,
        "ranked_on": (
            "Full-history expectancy after costs. Never on recent performance — "
            "ranking by the last thirty days promotes whatever just got lucky."
        ),
        "cohort_deflation": cohort,
        # Survivorship applies to every row, so it is stated once and
        # prominently rather than twelve times in small print.
        "universe_warning": (
            "Every backtest here runs on today's index membership. Companies that "
            "went bankrupt or were taken over are absent, so the absolute returns "
            "are far better than reality — most extremely for the momentum "
            "strategies, which buy whatever rose furthest. Compare each strategy "
            "against its own control, never against another's headline return."
        ),
    }


class Holding(BaseModel):
    ticker: str
    name: str
    quantity: float
    avg_cost: float
    opened_at: date
    last_price: float | None
    unrealised_pct: float | None
    # The rule that put it there, and the numbers that fired it.
    rule_fired: str
    metric_values: dict


class TradeRow(BaseModel):
    ticker: str
    side: str
    quantity: float
    price: float
    spread_cost: float
    commission: float
    signal_date: date
    fill_date: date
    rule_fired: str
    metric_values: dict


class StrategyDetail(BaseModel):
    strategy_id: str
    name: str
    hypothesis: str
    authority: str
    citation: str | None
    horizon: str
    status: str
    stage: str
    registered_at: date
    expected_trade_frequency: str
    expected_holding_period: str
    predicted_performance: str
    encoding_deviations: str | None
    decay_note: str
    parent_strategy_id: str | None
    duplicate_of: str | None
    duplicate_correlation: float | None
    duplicate_override_note: str | None
    rules_json: dict
    rules_plain: list[str]
    holdings: list[Holding]
    trades: list[TradeRow]
    equity_curve: list[tuple[str, float]]
    paper: dict
    backtest: dict | None
    # Paper lagging the backtest badly is the Quantopian warning sign.
    decay_warning: str | None


@router.get("/trades-today")
async def trades_today(session: SessionDep, on: date | None = None) -> dict:
    """What every strategy did this morning, and why.

    Defaults to the most recent fill date rather than today's calendar date,
    so the view is useful at a weekend instead of empty.
    """
    if on is None:
        on = (await session.execute(select(func.max(PaperTrade.fill_date)))).scalar()
    if on is None:
        return {"date": None, "trades": [], "note": "No paper trades yet."}

    rows = list((
        await session.execute(
            select(PaperTrade, registry.Strategy.name)
            .join(registry.Strategy, registry.Strategy.strategy_id == PaperTrade.strategy_id)
            .where(PaperTrade.fill_date == on)
            .order_by(registry.Strategy.name, PaperTrade.ticker)
        )
    ).all())
    return {
        "date": on,
        "trades": [
            {
                "strategy_id": str(trade.strategy_id),
                "strategy": name,
                "ticker": trade.ticker,
                "side": trade.side,
                "quantity": float(trade.quantity),
                "price": float(trade.price),
                "costs": float(trade.spread_cost) + float(trade.commission),
                "signal_date": trade.signal_date,
                "rule_fired": trade.rule_fired,
                "metric_values": trade.metric_values,
            }
            for trade, name in rows
        ],
    }


@router.get("/{strategy_id}")
async def detail(strategy_id: uuid.UUID, session: SessionDep) -> StrategyDetail:
    strategy = await session.get(registry.Strategy, strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail=f"unknown strategy {strategy_id}")

    rules = parse_rules(strategy.rules)
    positions = list((
        await session.execute(
            select(PaperPosition).where(PaperPosition.strategy_id == strategy_id)
            .order_by(PaperPosition.ticker)
        )
    ).scalars())

    names = dict((
        await session.execute(
            select(Security.ticker, Security.name)
            .where(Security.ticker.in_([p.ticker for p in positions] or ["-"]))
        )
    ).all())

    holdings = []
    for position in positions:
        last = (
            await session.execute(
                select(PriceDaily.adjusted_close)
                .where(PriceDaily.ticker == position.ticker,
                       PriceDaily.adjusted_close.is_not(None))
                .order_by(PriceDaily.date.desc()).limit(1)
            )
        ).scalar()
        price = float(last) if last is not None else None
        holdings.append(Holding(
            ticker=position.ticker,
            name=names.get(position.ticker, position.ticker),
            quantity=float(position.quantity),
            avg_cost=float(position.avg_cost),
            opened_at=position.opened_at,
            last_price=price,
            unrealised_pct=(
                round((price / float(position.avg_cost) - 1) * 100, 2)
                if price and float(position.avg_cost) > 0 else None
            ),
            rule_fired=position.rule_fired,
            metric_values=position.metric_values,
        ))

    trades = list((
        await session.execute(
            select(PaperTrade).where(PaperTrade.strategy_id == strategy_id)
            .order_by(desc(PaperTrade.fill_date), PaperTrade.ticker)
        )
    ).scalars())
    curve = list((
        await session.execute(
            select(PaperEquityDaily.date, PaperEquityDaily.equity)
            .where(PaperEquityDaily.strategy_id == strategy_id)
            .order_by(PaperEquityDaily.date)
        )
    ).all())

    paper = await _paper_stats(session, strategy_id)
    backtest = await _latest_backtest(session, strategy_id)
    results = backtest.results if backtest else None

    # The Quantopian warning sign: paper materially behind the backtest.
    warning = None
    if results and paper["trades"] >= 20:
        expected = (results.get("overall") or {}).get("mean_trade_return_pct")
        realised = paper.get("total_return_pct")
        if expected is not None and realised is not None and paper["months"] >= 6:
            annualised_backtest = (results.get("overall") or {}).get("total_return_pct")
            if annualised_backtest and realised < annualised_backtest * 0.3:
                warning = (
                    "Paper trading is running far behind the backtest. That gap is "
                    "the single most common sign that a backtest was fitted to its "
                    "own history rather than finding something real."
                )

    return StrategyDetail(
        strategy_id=str(strategy.strategy_id),
        name=strategy.name,
        hypothesis=strategy.hypothesis,
        authority=strategy.authority,
        citation=strategy.citation,
        horizon=strategy.horizon,
        status=strategy.status,
        stage=strategy.stage,
        registered_at=strategy.registered_at.date(),
        expected_trade_frequency=strategy.expected_trade_frequency,
        expected_holding_period=strategy.expected_holding_period,
        predicted_performance=strategy.predicted_performance,
        encoding_deviations=strategy.encoding_deviations,
        decay_note=strategy.decay_note,
        parent_strategy_id=str(strategy.parent_strategy_id) if strategy.parent_strategy_id else None,
        duplicate_of=str(strategy.duplicate_of) if strategy.duplicate_of else None,
        duplicate_correlation=(
            float(strategy.duplicate_correlation) if strategy.duplicate_correlation else None
        ),
        duplicate_override_note=strategy.duplicate_override_note,
        rules_json=strategy.rules,
        rules_plain=describe(rules),
        holdings=holdings,
        trades=[TradeRow(
            ticker=t.ticker, side=t.side, quantity=float(t.quantity), price=float(t.price),
            spread_cost=float(t.spread_cost), commission=float(t.commission),
            signal_date=t.signal_date, fill_date=t.fill_date,
            rule_fired=t.rule_fired, metric_values=t.metric_values,
        ) for t in trades],
        equity_curve=[(d.isoformat(), float(e)) for d, e in curve],
        paper={k: v for k, v in paper.items() if k != "monthly_returns"},
        backtest=results,
        decay_warning=warning,
    )


class PromoteRequest(BaseModel):
    stage: str = Field(pattern="^(paper|proven)$")
    note: str | None = None


@router.post("/{strategy_id}/promote")
async def promote(strategy_id: uuid.UUID, body: PromoteRequest, session: SessionDep) -> dict:
    """Promotion is a human act. The gate can say a strategy is eligible; only
    this endpoint, called by Roger, moves it."""
    strategy = await session.get(registry.Strategy, strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail=f"unknown strategy {strategy_id}")

    if body.stage == "paper":
        backtest = await _latest_backtest(session, strategy_id)
        if backtest is None:
            raise HTTPException(status_code=409, detail="no backtest has been run")
        gate = backtest.results.get("gate", {})
        if not gate.get("eligible_for_paper"):
            raise HTTPException(
                status_code=409,
                detail="backtest gate not passed: " + "; ".join(gate.get("blocking_reasons", [])),
            )
        await registry.promote(session, strategy_id, "paper", body.note)
        try:
            await registry.activate(session, strategy_id)
        except registry.ActivationBlocked as exc:
            await session.commit()
            raise HTTPException(status_code=409, detail=str(exc))
    else:
        await registry.promote(session, strategy_id, body.stage, body.note)

    await session.commit()
    return {"strategy_id": str(strategy_id), "stage": body.stage}


class LifecycleRequest(BaseModel):
    reason: str


@router.post("/{strategy_id}/pause")
async def pause(strategy_id: uuid.UUID, body: LifecycleRequest, session: SessionDep) -> dict:
    await registry.pause(session, strategy_id, body.reason)
    await session.commit()
    return {"strategy_id": str(strategy_id), "status": "paused"}


@router.post("/{strategy_id}/retire")
async def retire(strategy_id: uuid.UUID, body: LifecycleRequest, session: SessionDep) -> dict:
    await registry.retire(session, strategy_id, body.reason)
    await session.commit()
    return {"strategy_id": str(strategy_id), "status": "retired"}


@router.post("/{strategy_id}/activate")
async def activate(
    strategy_id: uuid.UUID, session: SessionDep, override_note: str | None = None
) -> dict:
    try:
        await registry.activate(session, strategy_id, override_note)
    except registry.ActivationBlocked as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await session.commit()
    return {"strategy_id": str(strategy_id), "status": "active"}
