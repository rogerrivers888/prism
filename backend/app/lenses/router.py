from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.fundamentals import sector_of
from app.lenses.base import SCORING_VERSION, dispersion
from app.lenses.engine import (
    LENS_BY_NAME,
    score_history,
    score_ticker,
    stored_scores,
)

router = APIRouter(prefix="/lenses", tags=["lenses"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


class LensScoreOut(BaseModel):
    lens: str
    score: float | None
    coverage: float
    applicable: bool
    inputs: dict


class LensScoresOut(BaseModel):
    ticker: str
    as_of: date
    scoring_version: str
    # Where the methodologies disagree. NULL below three usable lenses.
    dispersion: float | None
    # False when nothing was stored for this date and the scores were
    # computed on the fly, which is the normal case before the nightly job
    # has run. Computed results are not persisted by a read request.
    stored: bool
    scores: list[LensScoreOut]


class LensHistoryPointOut(BaseModel):
    as_of: date
    score: float | None
    coverage: float
    applicable: bool


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

    return LensScoresOut(
        ticker=ticker,
        as_of=as_of,
        scoring_version=SCORING_VERSION,
        dispersion=dispersion(scores),
        stored=stored,
        scores=[
            LensScoreOut(
                lens=s.lens,
                score=s.score,
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
            coverage=float(row.coverage),
            applicable=row.applicable,
        )
        for row in rows
    ]
