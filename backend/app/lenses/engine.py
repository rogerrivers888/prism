"""Lens scoring engine.

The scoring itself (``evaluate_lens``) is pure: metrics in, scores out, no
database. The database layer below only gathers inputs and persists results,
so every scoring rule is unit-testable without a session.
"""

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from statistics import median

from sqlalchemy import Boolean, Date, Integer, Numeric, Text, select
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.fundamentals import (
    all_securities,
    metric_history_as_of,
    metrics_as_of,
    price_history_as_of,
    sector_of,
    tickers_in_sector,
)
from app.lenses import cycle, growth, momentum, quality, trend, value
from app.lenses import guards
from app.lenses.derived import SOURCE_METRICS, derive_all
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
    # Secondary reading: the same lens against declared bands only.
    score_absolute: Mapped[Decimal | None] = mapped_column(Numeric)
    relative_premium: Mapped[Decimal | None] = mapped_column(Numeric)


class SectorLensDaily(Base):
    """Median lens readings per sector per day.

    The absolute median is the one that matters: peer percentiles are
    normalised within a sector by construction, so they can never reveal that
    the sector as a whole is stretched.
    """

    __tablename__ = "sector_lens_daily"

    sector: Mapped[str] = mapped_column(Text, primary_key=True)
    as_of: Mapped[date] = mapped_column(Date, primary_key=True)
    lens: Mapped[str] = mapped_column(Text, primary_key=True)
    scoring_version: Mapped[str] = mapped_column(Text, primary_key=True)
    median_score: Mapped[Decimal | None] = mapped_column(Numeric)
    median_score_absolute: Mapped[Decimal | None] = mapped_column(Numeric)
    median_relative_premium: Mapped[Decimal | None] = mapped_column(Numeric)
    member_count: Mapped[int] = mapped_column(Integer, nullable=False)


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
            "display_only": list(lens.display_only),
                "reason": "lens_not_applicable_to_sector",
                "metrics": {},
                "flags": [],
            },
        )

    outcomes: dict[str, MetricOutcome] = {}
    subscores: dict[str, float] = {}
    absolute_subscores: dict[str, float] = {}

    for spec in lens.metrics:
        excluded = guards.check(spec, sector, metrics)
        raw = metrics.get(spec.name)

        if not spec.scored:
            # Fetched and returned for the UI, never scored, and absent from
            # the coverage denominator. The guard verdict is still recorded so
            # a consumer knows whether the figure is meaningful for the sector.
            outcomes[spec.name] = MetricOutcome(
                value=raw, excluded=excluded, scored=False
            )
            continue

        if excluded is not None:
            # Excluded metrics reduce coverage rather than scoring zero.
            outcomes[spec.name] = MetricOutcome(value=raw, excluded=excluded)
            continue
        if raw is None:
            outcomes[spec.name] = MetricOutcome(excluded="not_available")
            continue

        # The band reading is always computed, whether or not it is the one
        # that counts, so both perspectives are on the record.
        absolute = band_score(spec, raw)

        peer_values = list(peers.get(spec.name, ()))
        if len(peer_values) >= MIN_PEERS:
            subscore = percentile_score(spec, raw, peer_values)
            method, peer_count = METHOD_PERCENTILE, len(peer_values)
        else:
            # Too few peers for a percentile to mean anything; fall back to
            # the lens's declared absolute bands.
            subscore = absolute
            method, peer_count = METHOD_BANDS, len(peer_values)

        outcomes[spec.name] = MetricOutcome(
            value=raw,
            score=subscore,
            score_absolute=absolute,
            method=method,
            peer_count=peer_count,
        )
        subscores[spec.name] = subscore
        absolute_subscores[spec.name] = absolute

    # Only scored metrics count: a display-only metric must not be able to
    # dilute coverage by being absent, nor inflate it by being present.
    declared = len(lens.scored_metrics)
    coverage = len(subscores) / declared if declared else 0.0
    usable = coverage >= MIN_COVERAGE and subscores
    score = lens.combine(subscores) if usable else None
    # Same coverage rule governs both: a band reading built on two of five
    # inputs is no more trustworthy than a peer reading on the same two.
    score_absolute = lens.combine(absolute_subscores) if usable else None

    return LensScore(
        ticker=ticker,
        as_of=as_of,
        lens=lens.name,
        score=None if score is None else round(score, 4),
        score_absolute=None if score_absolute is None else round(score_absolute, 4),
        coverage=round(coverage, 4),
        applicable=True,
        inputs={
            "sector": sector,
            "declared": list(lens.declared),
            "display_only": list(lens.display_only),
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


async def sector_metrics_as_of(
    session: AsyncSession, tickers: list[str], as_of: date
) -> dict[str, dict[str, float]]:
    """Ingested metrics plus derived ones, for a whole sector, as known on as_of.

    Derivation happens here rather than inside scoring so that evaluate_lens
    stays pure, and before peer sets are built so a derived metric can be
    percentile-ranked like any other. Both reads apply published_at <= as_of
    inside app.fundamentals and cannot skip it.
    """
    metrics = await metrics_as_of(session, tickers, as_of)
    history = await metric_history_as_of(session, tickers, list(SOURCE_METRICS), as_of)
    prices = await price_history_as_of(session, tickers, as_of)
    for ticker, values in metrics.items():
        derived = derive_all(history.get(ticker, {}), prices.get(ticker, ()))
        for name, computed in derived.items():
            # An explicitly ingested figure wins, so deriving never silently
            # overwrites something the source actually reported.
            values.setdefault(name, computed)
    return metrics


async def score_ticker(
    session: AsyncSession, ticker: str, as_of: date
) -> list[LensScore]:
    """Score every lens for one ticker as of a date. Computes, does not persist."""
    sector = await sector_of(session, ticker)
    if sector is None:
        return []

    peers_tickers = await tickers_in_sector(session, sector)
    sector_metrics = await sector_metrics_as_of(session, peers_tickers, as_of)
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
        sector_metrics = await sector_metrics_as_of(session, tickers, as_of)
        peers = peer_values(sector_metrics)
        by_lens: dict[str, list[LensScore]] = {}
        for ticker in tickers:
            scores = evaluate_all(
                ticker, as_of, sector, sector_metrics.get(ticker, {}), peers
            )
            for result in scores:
                await _upsert(session, result)
                by_lens.setdefault(result.lens, []).append(result)
                written += 1
            await _upsert_dispersion(session, ticker, as_of, scores)
        await _upsert_sector_medians(session, sector, as_of, by_lens)
    await session.flush()
    return written


def _median(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return round(median(values), 4)


async def _upsert_sector_medians(
    session: AsyncSession,
    sector: str,
    as_of: date,
    by_lens: dict[str, list[LensScore]],
) -> None:
    for lens, results in by_lens.items():
        usable = [r for r in results if r.applicable and r.score is not None]
        columns = {
            "median_score": _median([r.score for r in usable]),
            "median_score_absolute": _median(
                [r.score_absolute for r in usable if r.score_absolute is not None]
            ),
            "median_relative_premium": _median(
                [
                    r.relative_premium
                    for r in usable
                    if r.relative_premium is not None
                ]
            ),
            "member_count": len(usable),
        }
        statement = insert(SectorLensDaily).values(
            sector=sector,
            as_of=as_of,
            lens=lens,
            scoring_version=SCORING_VERSION,
            **columns,
        )
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=["sector", "as_of", "lens", "scoring_version"],
                set_=columns,
            )
        )


async def _upsert(session: AsyncSession, result: LensScore) -> None:
    statement = insert(LensScoreDaily).values(
        ticker=result.ticker,
        as_of=result.as_of,
        lens=result.lens,
        scoring_version=result.scoring_version,
        score=result.score,
        score_absolute=result.score_absolute,
        relative_premium=result.relative_premium,
        coverage=result.coverage,
        applicable=result.applicable,
        inputs=result.inputs,
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["ticker", "as_of", "lens", "scoring_version"],
            set_={
                "score": statement.excluded.score,
                "score_absolute": statement.excluded.score_absolute,
                "relative_premium": statement.excluded.relative_premium,
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
            score_absolute=(
                None if row.score_absolute is None else float(row.score_absolute)
            ),
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
    "SectorLensDaily",
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


async def sector_medians(
    session: AsyncSession,
    sector: str,
    as_of: date,
    scoring_version: str = SCORING_VERSION,
) -> list[SectorLensDaily]:
    return list(
        (
            await session.execute(
                select(SectorLensDaily).where(
                    SectorLensDaily.sector == sector,
                    SectorLensDaily.as_of == as_of,
                    SectorLensDaily.scoring_version == scoring_version,
                )
            )
        ).scalars()
    )
