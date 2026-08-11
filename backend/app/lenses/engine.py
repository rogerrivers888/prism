"""Lens scoring engine.

The scoring itself (``evaluate_lens``) is pure: metrics in, scores out, no
database. The database layer below only gathers inputs and persists results,
so every scoring rule is unit-testable without a session.
"""

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, Integer, Numeric, Text, select
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.fundamentals import (
    all_securities,
    metrics_as_of,
    sector_of,
    tickers_in_sector,
)
from app.lenses import cycle, growth, momentum, quality, trend, value
from app.lenses import guards
from app.lenses.base import (
    METHOD_BANDS,
    METHOD_PERCENTILE,
    MIN_COVERAGE,
    MIN_PEERS,
    SCORING_VERSION,
    Lens,
    LensScore,
    MetricOutcome,
    band_score,
    dispersion,
    percentile_score,
    usable_scores,
)

LENSES: tuple[Lens, ...] = (
    trend.LENS,
    growth.LENS,
    quality.LENS,
    value.LENS,
    momentum.LENS,
    cycle.LENS,
)

LENS_BY_NAME = {lens.name: lens for lens in LENSES}


class LensScoreDaily(Base):
    __tablename__ = "lens_scores_daily"

    ticker: Mapped[str] = mapped_column(Text, primary_key=True)
    as_of: Mapped[date] = mapped_column(Date, primary_key=True)
    lens: Mapped[str] = mapped_column(Text, primary_key=True)
    scoring_version: Mapped[str] = mapped_column(Text, primary_key=True)
    score: Mapped[Decimal | None] = mapped_column(Numeric)
    coverage: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    applicable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    inputs: Mapped[dict] = mapped_column(JSONB, nullable=False)


class DispersionDaily(Base):
    """One row per ticker per day — not per lens, hence its own table."""

    __tablename__ = "dispersion_daily"

    ticker: Mapped[str] = mapped_column(Text, primary_key=True)
    as_of: Mapped[date] = mapped_column(Date, primary_key=True)
    scoring_version: Mapped[str] = mapped_column(Text, primary_key=True)
    dispersion: Mapped[Decimal | None] = mapped_column(Numeric)
    usable_lenses: Mapped[int] = mapped_column(Integer, nullable=False)


# --------------------------------------------------------------------------
# Pure scoring
# --------------------------------------------------------------------------


def evaluate_lens(
    lens: Lens,
    ticker: str,
    as_of: date,
    sector: str,
    metrics: Mapping[str, float],
    peers: Mapping[str, Sequence[float]] | None = None,
) -> LensScore:
    """Score one lens for one ticker. Pure — no database access.

    ``metrics`` is every metric known for this ticker as of the date (guards
    consult metrics outside the lens's own declared inputs). ``peers`` maps a
    metric name to the values held by every sector member that has it,
    including this ticker.
    """
    peers = peers or {}

    if not lens.applies_to(sector):
        # No score, not a zero: the lens has nothing to say about this
        # business, which is different from saying it scores badly.
        return LensScore(
            ticker=ticker,
            as_of=as_of,
            lens=lens.name,
            score=None,
            coverage=0.0,
            applicable=False,
            inputs={
                "sector": sector,
                "declared": list(lens.declared),
                "reason": "lens_not_applicable_to_sector",
                "metrics": {},
                "flags": [],
            },
        )

    outcomes: dict[str, MetricOutcome] = {}
    subscores: dict[str, float] = {}

    for spec in lens.metrics:
        excluded = guards.check(spec, sector, metrics)
        raw = metrics.get(spec.name)

        if excluded is not None:
            # Excluded metrics reduce coverage rather than scoring zero.
            outcomes[spec.name] = MetricOutcome(value=raw, excluded=excluded)
            continue
        if raw is None:
            outcomes[spec.name] = MetricOutcome(excluded="not_available")
            continue

        peer_values = list(peers.get(spec.name, ()))
        if len(peer_values) >= MIN_PEERS:
            subscore = percentile_score(spec, raw, peer_values)
            method, peer_count = METHOD_PERCENTILE, len(peer_values)
        else:
            # Too few peers for a percentile to mean anything; fall back to
            # the lens's declared absolute bands.
            subscore = band_score(spec, raw)
            method, peer_count = METHOD_BANDS, len(peer_values)

        outcomes[spec.name] = MetricOutcome(
            value=raw, score=subscore, method=method, peer_count=peer_count
        )
        subscores[spec.name] = subscore

    declared = len(lens.metrics)
    coverage = len(subscores) / declared if declared else 0.0
    score = lens.combine(subscores) if coverage >= MIN_COVERAGE and subscores else None

    return LensScore(
        ticker=ticker,
        as_of=as_of,
        lens=lens.name,
        score=None if score is None else round(score, 4),
        coverage=round(coverage, 4),
        applicable=True,
        inputs={
            "sector": sector,
            "declared": list(lens.declared),
            "available": len(subscores),
            "metrics": {name: o.as_dict() for name, o in outcomes.items()},
            "flags": guards.flags(sector, metrics),
            "withheld": (
                "coverage_below_minimum" if score is None and subscores else None
            ),
        },
    )


def evaluate_all(
    ticker: str,
    as_of: date,
    sector: str,
    metrics: Mapping[str, float],
    peers: Mapping[str, Sequence[float]] | None = None,
) -> list[LensScore]:
    """Score every lens for one ticker. Pure."""
    return [
        evaluate_lens(lens, ticker, as_of, sector, metrics, peers) for lens in LENSES
    ]


def peer_values(
    sector_metrics: Mapping[str, Mapping[str, float]],
) -> dict[str, list[float]]:
    """Collect per-metric peer value lists from a sector's metric tables."""
    collected: dict[str, list[float]] = {}
    for values in sector_metrics.values():
        for metric, v in values.items():
            collected.setdefault(metric, []).append(v)
    return collected


# --------------------------------------------------------------------------
# Database-backed entry points
# --------------------------------------------------------------------------


async def score_ticker(
    session: AsyncSession, ticker: str, as_of: date
) -> list[LensScore]:
    """Score every lens for one ticker as of a date. Computes, does not persist."""
    sector = await sector_of(session, ticker)
    if sector is None:
        return []

    peers_tickers = await tickers_in_sector(session, sector)
    # One point-in-time read for the whole sector: published_at <= as_of is
    # applied inside metrics_as_of and cannot be skipped here.
    sector_metrics = await metrics_as_of(session, peers_tickers, as_of)
    metrics = sector_metrics.get(ticker, {})
    return evaluate_all(ticker, as_of, sector, metrics, peer_values(sector_metrics))


async def score_universe(session: AsyncSession, as_of: date) -> int:
    """Score every known security as of a date and persist. For the nightly job.

    Writes the lens scores and the derived dispersion figure together, so the
    two can never describe different runs. Returns the number of lens rows
    written (dispersion is one row per ticker on top). Re-running for the same
    date and scoring_version overwrites in place, so the job is safe to retry.
    """
    securities = await all_securities(session)
    by_sector: dict[str, list[str]] = {}
    for security in securities:
        by_sector.setdefault(security.sector, []).append(security.ticker)

    written = 0
    for sector, tickers in by_sector.items():
        sector_metrics = await metrics_as_of(session, tickers, as_of)
        peers = peer_values(sector_metrics)
        for ticker in tickers:
            scores = evaluate_all(
                ticker, as_of, sector, sector_metrics.get(ticker, {}), peers
            )
            for result in scores:
                await _upsert(session, result)
                written += 1
            await _upsert_dispersion(session, ticker, as_of, scores)
    await session.flush()
    return written


async def _upsert(session: AsyncSession, result: LensScore) -> None:
    statement = insert(LensScoreDaily).values(
        ticker=result.ticker,
        as_of=result.as_of,
        lens=result.lens,
        scoring_version=result.scoring_version,
        score=result.score,
        coverage=result.coverage,
        applicable=result.applicable,
        inputs=result.inputs,
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["ticker", "as_of", "lens", "scoring_version"],
            set_={
                "score": statement.excluded.score,
                "coverage": statement.excluded.coverage,
                "applicable": statement.excluded.applicable,
                "inputs": statement.excluded.inputs,
            },
        )
    )


async def _upsert_dispersion(
    session: AsyncSession, ticker: str, as_of: date, scores: Sequence[LensScore]
) -> None:
    statement = insert(DispersionDaily).values(
        ticker=ticker,
        as_of=as_of,
        scoring_version=SCORING_VERSION,
        dispersion=dispersion(scores),
        usable_lenses=len(usable_scores(scores)),
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["ticker", "as_of", "scoring_version"],
            set_={
                "dispersion": statement.excluded.dispersion,
                "usable_lenses": statement.excluded.usable_lenses,
            },
        )
    )


async def stored_dispersion(
    session: AsyncSession,
    ticker: str,
    as_of: date,
    scoring_version: str = SCORING_VERSION,
) -> DispersionDaily | None:
    return (
        await session.execute(
            select(DispersionDaily).where(
                DispersionDaily.ticker == ticker,
                DispersionDaily.as_of == as_of,
                DispersionDaily.scoring_version == scoring_version,
            )
        )
    ).scalar_one_or_none()


async def stored_scores(
    session: AsyncSession,
    ticker: str,
    as_of: date,
    scoring_version: str = SCORING_VERSION,
) -> list[LensScore]:
    rows = (
        await session.execute(
            select(LensScoreDaily).where(
                LensScoreDaily.ticker == ticker,
                LensScoreDaily.as_of == as_of,
                LensScoreDaily.scoring_version == scoring_version,
            )
        )
    ).scalars()
    return [
        LensScore(
            ticker=row.ticker,
            as_of=row.as_of,
            lens=row.lens,
            score=None if row.score is None else float(row.score),
            coverage=float(row.coverage),
            applicable=row.applicable,
            inputs=row.inputs,
            scoring_version=row.scoring_version,
        )
        for row in rows
    ]


async def score_history(
    session: AsyncSession,
    ticker: str,
    lens: str,
    date_from: date,
    date_to: date,
    scoring_version: str = SCORING_VERSION,
) -> list[LensScoreDaily]:
    return list(
        (
            await session.execute(
                select(LensScoreDaily)
                .where(
                    LensScoreDaily.ticker == ticker,
                    LensScoreDaily.lens == lens,
                    LensScoreDaily.as_of >= date_from,
                    LensScoreDaily.as_of <= date_to,
                    LensScoreDaily.scoring_version == scoring_version,
                )
                .order_by(LensScoreDaily.as_of)
            )
        ).scalars()
    )


__all__ = [
    "LENSES",
    "LENS_BY_NAME",
    "DispersionDaily",
    "LensScoreDaily",
    "dispersion",
    "stored_dispersion",
    "evaluate_all",
    "evaluate_lens",
    "peer_values",
    "score_history",
    "score_ticker",
    "score_universe",
    "stored_scores",
]
