from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.fundamentals import sector_of
from app.lenses.base import SCORING_VERSION, dispersion
from app.lenses.engine import (
    LENSES,
    LENS_BY_NAME,
    score_history,
    score_ticker,
    sector_medians,
    stored_dispersion,
    stored_scores,
)

router = APIRouter(prefix="/lenses", tags=["lenses"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


class BandOut(BaseModel):
    lens: str
    metric: str
    higher_is_better: bool
    description: str
    ev_or_ebitda_derived: bool
    # False for display-only metrics, whose band table is inert.
    scored: bool
    # Ascending by value; scores interpolate linearly between breakpoints and
    # clamp outside them.
    breakpoints: list[tuple[float, float]]


class LensScoreOut(BaseModel):
    lens: str
    # Peer-relative, and the headline. Unchanged by the absolute reading.
    score: float | None
    # The same lens against declared bands only, ignoring peers.
    score_absolute: float | None
    # score - score_absolute. Positive on value = cheap within an expensive
    # sector, which is the cyclical-peak trap.
    relative_premium: float | None
    coverage: float
    applicable: bool
    inputs: dict


class LensScoresOut(BaseModel):
    ticker: str
    as_of: date
    scoring_version: str
    # Where the methodologies disagree. NULL below three usable lenses.
    dispersion: float | None
    # False when nothing was stored for this date and the values were
    # computed on the fly, which is the normal case before the nightly job
    # has run. Computed results are not persisted by a read request.
    stored: bool
    dispersion_stored: bool
    scores: list[LensScoreOut]


class LensHistoryPointOut(BaseModel):
    as_of: date
    score: float | None
    score_absolute: float | None
    coverage: float
    applicable: bool


class SectorLensOut(BaseModel):
    sector: str
    lens: str
    median_score: float | None
    # The sector screen reads this: a low median absolute value score means
    # the whole sector is richly priced, which percentiles cannot reveal.
    median_score_absolute: float | None
    median_relative_premium: float | None
    member_count: int


# DEV-ONLY: the absolute band tables are the least evidence-backed part of the
# engine and are otherwise invisible outside the source. Exposed so they can be
# reviewed and argued with. Remove once the bands are settled.
#
# Declared before /{ticker} on purpose: FastAPI matches routes in definition
# order, so the reverse would make "bands" look like a ticker.
@router.get("/bands", tags=["dev (temporary)"])
async def get_bands() -> list[BandOut]:
    return [
        BandOut(
            lens=lens.name,
            metric=spec.name,
            higher_is_better=spec.higher_is_better,
            description=spec.description,
            ev_or_ebitda_derived=spec.ev_or_ebitda_derived,
            scored=spec.scored,
            breakpoints=[(float(v), float(s)) for v, s in spec.bands],
        )
        for lens in LENSES
        for spec in lens.metrics
    ]


@router.get("/{ticker}")
async def get_lens_scores(
    ticker: str, session: SessionDep, as_of: date | None = None
) -> LensScoresOut:
    as_of = as_of or date.today()

    if await sector_of(session, ticker) is None:
        raise HTTPException(status_code=404, detail=f"unknown ticker {ticker}")

    scores = await stored_scores(session, ticker, as_of)
    stored = bool(scores)
    if not scores:
        scores = await score_ticker(session, ticker, as_of)

    # Prefer the stored figure so the UI headline matches what the nightly job
    # recorded, but fall back to computing it rather than showing nothing.
    row = await stored_dispersion(session, ticker, as_of)
    spread = (
        float(row.dispersion)
        if row is not None and row.dispersion is not None
        else (None if row is not None else dispersion(scores))
    )

    return LensScoresOut(
        ticker=ticker,
        as_of=as_of,
        scoring_version=SCORING_VERSION,
        dispersion=spread,
        stored=stored,
        dispersion_stored=row is not None,
        scores=[
            LensScoreOut(
                lens=s.lens,
                score=s.score,
                score_absolute=s.score_absolute,
                relative_premium=s.relative_premium,
                coverage=s.coverage,
                applicable=s.applicable,
                inputs=s.inputs,
            )
            for s in sorted(scores, key=lambda s: s.lens)
        ],
    )


@router.get("/{ticker}/history")
async def get_lens_history(
    ticker: str,
    session: SessionDep,
    lens: Annotated[str, Query()],
    date_from: Annotated[date, Query(alias="from")],
    date_to: Annotated[date, Query(alias="to")],
) -> list[LensHistoryPointOut]:
    if lens not in LENS_BY_NAME:
        raise HTTPException(status_code=422, detail=f"unknown lens {lens}")
    if date_from > date_to:
        raise HTTPException(status_code=422, detail="from must not be after to")

    rows = await score_history(session, ticker, lens, date_from, date_to)
    return [
        LensHistoryPointOut(
            as_of=row.as_of,
            score=None if row.score is None else float(row.score),
            score_absolute=(
                None if row.score_absolute is None else float(row.score_absolute)
            ),
            coverage=float(row.coverage),
            applicable=row.applicable,
        )
        for row in rows
    ]


@router.get("/sectors/{sector}")
async def get_sector_lenses(
    sector: str, session: SessionDep, as_of: date | None = None
) -> list[SectorLensOut]:
    """Median lens readings for a whole sector on a date."""
    as_of = as_of or date.today()
    rows = await sector_medians(session, sector, as_of)
    if not rows:
        raise HTTPException(
            status_code=404, detail=f"no sector scores for {sector} on {as_of}"
        )
    return [
        SectorLensOut(
            sector=row.sector,
            lens=row.lens,
            median_score=None if row.median_score is None else float(row.median_score),
            median_score_absolute=(
                None
                if row.median_score_absolute is None
                else float(row.median_score_absolute)
            ),
            median_relative_premium=(
                None
                if row.median_relative_premium is None
                else float(row.median_relative_premium)
            ),
            member_count=row.member_count,
        )
        for row in sorted(rows, key=lambda r: r.lens)
    ]
