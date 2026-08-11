"""Screener, watchlist, research, book and decisions endpoints."""

import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import Text, cast, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.events import ConcurrencyError, append
from app.fundamentals import Security
from app.lenses.base import SCORING_VERSION
from app.lenses.engine import LENSES, DispersionDaily, LensScoreDaily, SectorLensDaily
from app.projections import catch_up
from app.projections.decisions import Decision
from app.projections.positions import Position
from app.projections.watchlist import WATCHLIST_STREAM, WatchlistEntry, entries

SessionDep = Annotated[AsyncSession, Depends(get_session)]

screener = APIRouter(prefix="/screener", tags=["screener"])
watchlist_router = APIRouter(prefix="/watchlist", tags=["watchlist"])
research = APIRouter(prefix="/research", tags=["research"])
book = APIRouter(prefix="/book", tags=["book"])
decisions_router = APIRouter(prefix="/decisions", tags=["decisions"])


# ---------------------------------------------------------------- screener


class SavedScreenIn(BaseModel):
    name: str
    filters: dict


class SavedScreenOut(BaseModel):
    id: int
    name: str
    filters: dict
    created_at: datetime


@screener.get("/saved")
async def list_saved(session: SessionDep) -> list[SavedScreenOut]:
    rows = (
        await session.execute(
            text("SELECT id, name, filters, created_at FROM saved_screens ORDER BY name")
        )
    ).all()
    return [
        SavedScreenOut(id=r[0], name=r[1], filters=r[2], created_at=r[3]) for r in rows
    ]


@screener.post("/saved")
async def save_screen(body: SavedScreenIn, session: SessionDep) -> SavedScreenOut:
    row = (
        await session.execute(
            text(
                """
                INSERT INTO saved_screens (name, filters) VALUES (:n, :f)
                ON CONFLICT (name) DO UPDATE SET filters = EXCLUDED.filters
                RETURNING id, name, filters, created_at
                """
            ).bindparams(n=body.name, f=__import__("json").dumps(body.filters)),
        )
    ).first()
    await session.commit()
    return SavedScreenOut(id=row[0], name=row[1], filters=row[2], created_at=row[3])


@screener.delete("/saved/{screen_id}")
async def delete_saved(screen_id: int, session: SessionDep) -> dict:
    await session.execute(
        text("DELETE FROM saved_screens WHERE id = :i").bindparams(i=screen_id)
    )
    await session.commit()
    return {"deleted": screen_id}


# --------------------------------------------------------------- watchlist


class WatchlistIn(BaseModel):
    ticker: str
    note: str | None = None


class WatchlistOut(BaseModel):
    ticker: str
    added_at: datetime
    note: str | None


async def _append_watchlist(session: AsyncSession, event_type: str, payload: dict):
    """Watchlist changes are events, so the order of attention is preserved."""
    await append(
        session,
        stream_id=WATCHLIST_STREAM,
        stream_type="watchlist",
        event_type=event_type,
        payload=payload,
        occurred_at=datetime.now(UTC),
        actor="roger",
    )
    await session.commit()
    await catch_up(session)
    await session.commit()


@watchlist_router.get("")
async def get_watchlist(session: SessionDep) -> list[WatchlistOut]:
    return [
        WatchlistOut(ticker=e.ticker, added_at=e.added_at, note=e.note)
        for e in await entries(session)
    ]


@watchlist_router.post("")
async def add_to_watchlist(body: WatchlistIn, session: SessionDep) -> dict:
    await _append_watchlist(
        session, "WatchlistAdded", {"ticker": body.ticker.upper(), "note": body.note}
    )
    return {"ticker": body.ticker.upper(), "watched": True}


@watchlist_router.delete("/{ticker}")
async def remove_from_watchlist(ticker: str, session: SessionDep) -> dict:
    await _append_watchlist(session, "WatchlistRemoved", {"ticker": ticker.upper()})
    return {"ticker": ticker.upper(), "watched": False}


# ---------------------------------------------------------------- research


class PointIn(BaseModel):
    scope_type: Literal["sector", "ticker"]
    scope_value: str
    stance: Literal["for", "against"]
    body: str
    source_title: str | None = None
    source_url: str | None = None
    pinned: bool = False


class PointOut(PointIn):
    id: int
    stress_test: str | None = None
    created_at: datetime


@research.get("/points")
async def list_points(
    session: SessionDep, scope_type: str | None = None, scope_value: str | None = None
) -> list[PointOut]:
    query = "SELECT id, scope_type, scope_value, stance, body, source_title, source_url, pinned, stress_test, created_at FROM research_points"
    clauses, params = [], {}
    if scope_type:
        clauses.append("scope_type = :st")
        params["st"] = scope_type
    if scope_value:
        clauses.append("scope_value = :sv")
        params["sv"] = scope_value
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    # Pinned points first: they are the ones that survived scrutiny.
    query += " ORDER BY pinned DESC, created_at DESC"
    rows = (await session.execute(text(query).bindparams(**params))).all()
    return [
        PointOut(
            id=r[0], scope_type=r[1], scope_value=r[2], stance=r[3], body=r[4],
            source_title=r[5], source_url=r[6], pinned=r[7], stress_test=r[8],
            created_at=r[9],
        )
        for r in rows
    ]


@research.post("/points")
async def create_point(body: PointIn, session: SessionDep) -> PointOut:
    row = (
        await session.execute(
            text(
                """
                INSERT INTO research_points
                  (scope_type, scope_value, stance, body, source_title, source_url, pinned)
                VALUES (:st, :sv, :stance, :body, :title, :url, :pinned)
                RETURNING id, created_at
                """
            ).bindparams(
                st=body.scope_type, sv=body.scope_value, stance=body.stance,
                body=body.body, title=body.source_title, url=body.source_url,
                pinned=body.pinned,
            )
        )
    ).first()
    await session.commit()
    return PointOut(id=row[0], created_at=row[1], **body.model_dump())


class PointPatch(BaseModel):
    body: str | None = None
    pinned: bool | None = None
    source_title: str | None = None
    source_url: str | None = None
    stress_test: str | None = None


@research.patch("/points/{point_id}")
async def update_point(point_id: int, patch: PointPatch, session: SessionDep) -> dict:
    fields = {k: v for k, v in patch.model_dump().items() if v is not None}
    if not fields:
        return {"updated": 0}
    assignments = ", ".join(f"{k} = :{k}" for k in fields)
    await session.execute(
        text(
            f"UPDATE research_points SET {assignments}, updated_at = now() WHERE id = :id"
        ).bindparams(id=point_id, **fields)
    )
    await session.commit()
    return {"updated": point_id}


@research.delete("/points/{point_id}")
async def delete_point(point_id: int, session: SessionDep) -> dict:
    await session.execute(
        text("DELETE FROM research_points WHERE id = :i").bindparams(i=point_id)
    )
    await session.commit()
    return {"deleted": point_id}


class ClipIn(BaseModel):
    title: str
    body: str
    url: str | None = None
    summary: str | None = None
    tickers: list[str] = Field(default_factory=list)


class ClipOut(ClipIn):
    id: int
    created_at: datetime


@research.get("/clips")
async def list_clips(session: SessionDep, q: str | None = None) -> list[ClipOut]:
    if q:
        # Full-text over title, summary and body via the generated tsvector.
        rows = (
            await session.execute(
                text(
                    """
                    SELECT id, title, body, url, summary, tickers, created_at
                    FROM research_clips
                    WHERE search @@ plainto_tsquery('english', :q)
                    ORDER BY ts_rank(search, plainto_tsquery('english', :q)) DESC
                    LIMIT 100
                    """
                ).bindparams(q=q)
            )
        ).all()
    else:
        rows = (
            await session.execute(
                text(
                    "SELECT id, title, body, url, summary, tickers, created_at "
                    "FROM research_clips ORDER BY created_at DESC LIMIT 100"
                )
            )
        ).all()
    return [
        ClipOut(
            id=r[0], title=r[1], body=r[2], url=r[3], summary=r[4],
            tickers=list(r[5] or []), created_at=r[6],
        )
        for r in rows
    ]


@research.post("/clips")
async def create_clip(body: ClipIn, session: SessionDep) -> ClipOut:
    row = (
        await session.execute(
            text(
                """
                INSERT INTO research_clips (title, body, url, summary, tickers)
                VALUES (:t, :b, :u, :s, :tk)
                RETURNING id, created_at
                """
            ).bindparams(
                t=body.title, b=body.body, u=body.url, s=body.summary,
                tk=body.tickers,
            )
        )
    ).first()
    await session.commit()
    return ClipOut(id=row[0], created_at=row[1], **body.model_dump())


@research.delete("/clips/{clip_id}")
async def delete_clip(clip_id: int, session: SessionDep) -> dict:
    await session.execute(
        text("DELETE FROM research_clips WHERE id = :i").bindparams(i=clip_id)
    )
    await session.commit()
    return {"deleted": clip_id}


@research.get("/sectors")
async def sector_aggregates(session: SessionDep, as_of: date | None = None) -> list[dict]:
    """Sector lens medians — the evidence a sector case is argued against."""
    if as_of is None:
        as_of = (
            await session.execute(
                select(func.max(SectorLensDaily.as_of)).where(
                    SectorLensDaily.scoring_version == SCORING_VERSION
                )
            )
        ).scalar()
    rows = (
        await session.execute(
            select(SectorLensDaily).where(
                SectorLensDaily.as_of == as_of,
                SectorLensDaily.scoring_version == SCORING_VERSION,
            )
        )
    ).scalars()
    return [
        {
            "sector": r.sector,
            "lens": r.lens,
            "median_score": None if r.median_score is None else float(r.median_score),
            "median_score_absolute": (
                None if r.median_score_absolute is None else float(r.median_score_absolute)
            ),
            "median_relative_premium": (
                None
                if r.median_relative_premium is None
                else float(r.median_relative_premium)
            ),
            "member_count": r.member_count,
        }
        for r in rows
    ]


# -------------------------------------------------------------------- book


class PositionOut(BaseModel):
    stream_id: uuid.UUID
    ticker: str
    name: str | None
    sector: str | None
    instrument_type: str
    direction: str
    size: float
    entry_price: float
    current_stop: float | None
    initial_risk: float | None
    current_risk: float | None
    currency: str
    sleeve: str | None
    status: str
    opened_at: datetime
    # Spread bets control far more than the margin posted, so notional is
    # shown separately rather than folded into one exposure number.
    notional: float


class BookOut(BaseModel):
    positions: list[PositionOut]
    committed_capital: float | None
    total_notional: float
    total_risk: float
    # Positions sharing a driver are one bet wearing several names. Sector is
    # a coarse proxy for that driver, and deliberately labelled as such.
    clusters: list[dict]


@book.get("")
async def get_book(session: SessionDep, committed_capital: float | None = None) -> BookOut:
    rows = (
        await session.execute(
            select(Position).where(Position.status == "open").order_by(Position.opened_at)
        )
    ).scalars().all()

    tickers = {p.ticker for p in rows}
    meta = {
        t: (n, s)
        for t, n, s in (
            await session.execute(
                select(Security.ticker, Security.name, Security.sector).where(
                    Security.ticker.in_(tickers or {""})
                )
            )
        ).all()
    }

    out = []
    for p in rows:
        notional = float(p.size) * float(p.entry_price)
        name, sector = meta.get(p.ticker, (None, None))
        out.append(
            PositionOut(
                stream_id=p.stream_id, ticker=p.ticker, name=name, sector=sector,
                instrument_type=p.instrument_type, direction=p.direction,
                size=float(p.size), entry_price=float(p.entry_price),
                current_stop=float(p.current_stop) if p.current_stop else None,
                initial_risk=float(p.initial_risk) if p.initial_risk else None,
                current_risk=float(p.current_risk) if p.current_risk else None,
                currency=p.currency, sleeve=p.sleeve, status=p.status,
                opened_at=p.opened_at, notional=notional,
            )
        )

    clusters: dict[str, dict] = {}
    for position in out:
        key = position.sector or "unclassified"
        cluster = clusters.setdefault(
            key, {"driver": key, "positions": [], "notional": 0.0, "risk": 0.0}
        )
        cluster["positions"].append(position.ticker)
        cluster["notional"] += position.notional
        cluster["risk"] += position.current_risk or 0.0

    return BookOut(
        positions=out,
        committed_capital=committed_capital,
        total_notional=sum(p.notional for p in out),
        total_risk=sum(p.current_risk or 0.0 for p in out),
        clusters=sorted(clusters.values(), key=lambda c: -c["notional"]),
    )


class TradeIn(BaseModel):
    stream_id: uuid.UUID | None = None
    instrument: str
    instrument_type: Literal["spreadbet", "option", "share"]
    side: Literal["buy", "sell"]
    quantity: float
    price: float
    currency: str = "GBP"
    stop: float | None = None
    sleeve: Literal["high_growth", "deeply_undervalued"] | None = None
    occurred_at: datetime


@book.post("/trades")
async def record_trade(body: TradeIn, session: SessionDep) -> dict:
    """The first real write path to the event store from the UI."""
    stream_id = body.stream_id or uuid.uuid4()
    payload = {
        "instrument": body.instrument.upper(),
        "instrument_type": body.instrument_type,
        "side": body.side,
        "quantity": str(body.quantity),
        "price": str(body.price),
        "currency": body.currency,
    }
    if body.stop is not None:
        payload["stop"] = str(body.stop)
    if body.sleeve is not None:
        payload["sleeve"] = body.sleeve

    try:
        event = await append(
            session,
            stream_id=stream_id,
            stream_type="position",
            event_type="TradeExecuted",
            payload=payload,
            occurred_at=body.occurred_at,
            actor="roger",
        )
    except ConcurrencyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await session.commit()
    await catch_up(session)
    await session.commit()
    return {"stream_id": str(stream_id), "event_id": event.id}


# --------------------------------------------------------------- decisions


class DecisionIn(BaseModel):
    ticker: str | None = None
    kind: Literal["buy", "sell", "trim", "add", "hold"]
    thesis: str
    premortem: str
    falsifier: str
    sizing_note: str | None = None


class DecisionCloseIn(BaseModel):
    decision_quality: Literal["good", "bad"]
    outcome_quality: Literal["good", "bad", "neutral"]
    error_tag: Literal[
        "analytical", "informational", "behavioural", "sizing", "timing", "none"
    ]
    note: str | None = None


class DecisionOut(BaseModel):
    stream_id: uuid.UUID
    ticker: str | None
    kind: str
    status: str
    thesis: str
    premortem: str
    falsifier: str
    sizing_note: str | None
    declined_reason: str | None
    decision_quality: str | None
    outcome_quality: str | None
    error_tag: str | None
    close_note: str | None
    raised_at: datetime
    resolved_at: datetime | None
    closed_at: datetime | None


async def _append_decision(
    session: AsyncSession, stream_id: uuid.UUID, event_type: str, payload: dict
):
    await append(
        session,
        stream_id=stream_id,
        stream_type="decision",
        event_type=event_type,
        payload=payload,
        occurred_at=datetime.now(UTC),
        actor="roger",
    )
    await session.commit()
    await catch_up(session)
    await session.commit()


@decisions_router.get("")
async def list_decisions(session: SessionDep) -> list[DecisionOut]:
    rows = (
        await session.execute(select(Decision).order_by(Decision.raised_at.desc()))
    ).scalars()
    return [DecisionOut(**{c.name: getattr(r, c.name) for c in Decision.__table__.columns if c.name != "last_event_id"}) for r in rows]


@decisions_router.post("")
async def raise_decision(body: DecisionIn, session: SessionDep) -> dict:
    stream_id = uuid.uuid4()
    await _append_decision(session, stream_id, "DecisionRaised", body.model_dump())
    return {"stream_id": str(stream_id)}


@decisions_router.post("/{stream_id}/take")
async def take_decision(stream_id: uuid.UUID, session: SessionDep, note: str | None = None) -> dict:
    await _append_decision(session, stream_id, "DecisionTaken", {"note": note})
    return {"stream_id": str(stream_id), "status": "taken"}


@decisions_router.post("/{stream_id}/decline")
async def decline_decision(
    stream_id: uuid.UUID, session: SessionDep, reason: Annotated[str, Query()]
) -> dict:
    await _append_decision(session, stream_id, "DecisionDeclined", {"reason": reason})
    return {"stream_id": str(stream_id), "status": "declined"}


@decisions_router.post("/{stream_id}/close")
async def close_decision(
    stream_id: uuid.UUID, body: DecisionCloseIn, session: SessionDep
) -> dict:
    await _append_decision(session, stream_id, "DecisionClosed", body.model_dump())
    return {"stream_id": str(stream_id), "status": "closed"}


@decisions_router.get("/{stream_id}/audit")
async def decision_audit(stream_id: uuid.UUID, session: SessionDep) -> list[dict]:
    """Raw event stream. occurred_at and recorded_at both shown: when it
    happened and when we were told are different facts."""
    from app.events import read_stream

    return [
        {
            "id": e.id,
            "seq": e.seq,
            "event_type": e.event_type,
            "payload": e.payload,
            "occurred_at": e.occurred_at,
            "recorded_at": e.recorded_at,
            "actor": e.actor,
        }
        for e in await read_stream(session, stream_id)
    ]
