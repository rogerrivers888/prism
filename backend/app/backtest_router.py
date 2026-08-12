"""Backtest endpoints.

Every response carries its caveats inside the payload rather than beside it,
so a client cannot render the numbers without also having the reasons not to
trust them. The sweep endpoint exists because testing one combination and
reporting it is how a null result becomes a strategy.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.backtest import Costs, run_pre_earnings
from app.db import Base, get_session

router = APIRouter(prefix="/backtest", tags=["backtest"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    strategy: Mapped[str]
    params: Mapped[dict] = mapped_column(JSONB)
    results: Mapped[dict] = mapped_column(JSONB)
    variants_tested: Mapped[int]


class PreEarningsRequest(BaseModel):
    enter_days_before: int = Field(default=10, ge=1, le=60)
    exit_days_before: int = Field(default=2, ge=0, le=59)
    start: date = date(2010, 1, 1)
    end: date = date(2026, 8, 1)
    spread_bps: float = Field(default=10.0, ge=0)
    commission_bps: float = Field(default=5.0, ge=0)
    funding_annual_pct: float = Field(default=0.0, ge=0)
    leveraged: bool = False
    variants_tested: int = Field(default=1, ge=1)
    persist: bool = True


@router.post("/pre-earnings")
async def post_pre_earnings(body: PreEarningsRequest, session: SessionDep) -> dict:
    if body.enter_days_before <= body.exit_days_before:
        raise HTTPException(
            status_code=422,
            detail="enter_days_before must be greater than exit_days_before",
        )
    result = await run_pre_earnings(
        session,
        enter_days_before=body.enter_days_before,
        exit_days_before=body.exit_days_before,
        start=body.start,
        end=body.end,
        costs=Costs(
            spread_bps=body.spread_bps,
            commission_bps=body.commission_bps,
            funding_annual_pct=body.funding_annual_pct,
            leveraged=body.leveraged,
        ),
        variants_tested=body.variants_tested,
    )
    if body.persist:
        session.add(
            BacktestRun(
                strategy=result["strategy"],
                params=result["params"],
                results=result,
                variants_tested=body.variants_tested,
            )
        )
        await session.commit()
    return result


# Kept small on purpose: a sweep is several full backtests and each one walks
# every ticker's price history.
SWEEP_LIMIT = 12


class SweepRequest(BaseModel):
    enter_days: list[int] = Field(default=[5, 10, 20])
    exit_days: list[int] = Field(default=[1, 3])
    start: date = date(2010, 1, 1)
    end: date = date(2026, 8, 1)
    spread_bps: float = 10.0
    commission_bps: float = 5.0


@router.post("/pre-earnings/sweep")
async def post_sweep(body: SweepRequest, session: SessionDep) -> dict:
    combos = [
        (e, x) for e in sorted(set(body.enter_days)) for x in sorted(set(body.exit_days)) if e > x
    ]
    if not combos:
        raise HTTPException(status_code=422, detail="no valid combinations: enter must exceed exit")
    if len(combos) > SWEEP_LIMIT:
        raise HTTPException(
            status_code=422,
            detail=f"{len(combos)} combinations exceeds the limit of {SWEEP_LIMIT}",
        )

    costs = Costs(spread_bps=body.spread_bps, commission_bps=body.commission_bps)
    variants = []
    for enter, exit_ in combos:
        result = await run_pre_earnings(
            session, enter, exit_, body.start, body.end, costs, variants_tested=len(combos)
        )
        variants.append(
            {
                "enter_days_before": enter,
                "exit_days_before": exit_,
                "trades": result["overall"].get("trades", 0),
                "mean_return_pct": result["overall"].get("mean_return_pct"),
                "median_return_pct": result["overall"].get("median_return_pct"),
                "win_rate": result["overall"].get("win_rate"),
                "drift_pct": result["control_unconditional_drift"].get("mean_return_pct"),
                "excess_over_drift_pct": result["excess_over_drift_pct"],
                "excess_significance": result["excess_significance"],
            }
        )
        session.add(
            BacktestRun(
                strategy=result["strategy"],
                params=result["params"],
                results=result,
                variants_tested=len(combos),
            )
        )
    await session.commit()

    scored = [v for v in variants if v["excess_over_drift_pct"] is not None]
    best = max(scored, key=lambda v: v["excess_over_drift_pct"]) if scored else None
    negatives = sum(1 for v in scored if v["excess_over_drift_pct"] < 0)

    return {
        "variants_tested": len(combos),
        "variants": variants,
        "best": best,
        # The honest summary of a sweep is not the winner. It is whether the
        # winner's neighbours agree with it. A real effect varies smoothly with
        # the parameter; noise changes sign between adjacent settings.
        "verdict": {
            "negative_variants": negatives,
            "total_variants": len(scored),
            "mean_excess_pct": (
                round(sum(v["excess_over_drift_pct"] for v in scored) / len(scored), 4)
                if scored
                else None
            ),
            "best_inside_noise": (
                best["excess_significance"]["inside_noise"]
                if best and best["excess_significance"]
                else None
            ),
            "coherent": negatives == 0 or negatives == len(scored),
        },
    }


@router.get("/runs")
async def list_runs(session: SessionDep, limit: Annotated[int, Query(le=100)] = 20) -> list[dict]:
    rows = (
        await session.execute(
            select(BacktestRun).order_by(BacktestRun.id.desc()).limit(limit)
        )
    ).scalars()
    return [
        {
            "id": r.id,
            "strategy": r.strategy,
            "params": r.params,
            "variants_tested": r.variants_tested,
            "overall": r.results.get("overall"),
            "excess_over_drift_pct": r.results.get("excess_over_drift_pct"),
        }
        for r in rows
    ]


@router.get("/runs/{run_id}")
async def get_run(run_id: int, session: SessionDep) -> dict:
    row = await session.get(BacktestRun, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no run {run_id}")
    return row.results
