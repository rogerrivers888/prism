"""IG endpoints: two accounts, two regimes, never blended.

The one rule this router enforces above all others: there is no total across
accounts. A pension and a leveraged spread bet book are different kinds of
money with different failure modes, and a combined number at the top of the
page would be the single most misleading figure in Prism.
"""

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.fundamentals import PriceDaily, Security
from app.ig import funding as funding_module
from app.ig import reconcile as reconcile_module
from app.ig.models import (
    FundingAccrual,
    IGAccount,
    IGBalance,
    IGEpicMap,
    IGPosition,
    IGReconciliation,
    OptionMark,
    OptionPosition,
)
from app.options.analysis import analyse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ig", tags=["ig"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]

# How long Roger says he holds a leveraged position. Drives the projected
# funding figure; adjustable per request.
DEFAULT_HORIZON_DAYS = 105


class AccountOut(BaseModel):
    account_id: str
    type: str
    regime: str
    label: str | None
    currency: str | None
    balance: float | None
    margin_used: float | None
    available: float | None
    profit_loss: float | None


class PositionOut(BaseModel):
    deal_id: str
    epic: str
    ticker: str | None
    name: str | None
    kind: str
    direction: str
    size: float
    open_level: float | None
    current_level: float | None
    currency: str | None
    stop_level: float | None
    notional: float | None
    opened_at: datetime | None
    needs_mapping: bool
    # Leveraged accounts only; None on the pension where it does not exist.
    funding_paid_to_date: float | None = None
    funding_per_month: float | None = None
    funding_projected: float | None = None
    funding_is_estimate: bool = True


class OptionOut(BaseModel):
    deal_id: str
    underlying: str | None
    right: str
    strike: float
    expiry: date
    days_left: int
    contracts: float
    multiplier: float
    direction: str
    currency: str
    mark: float | None
    spot: float | None
    position_value: float | None
    premium_paid: float | None
    # The four numbers, in plain English.
    breakeven_line: str
    decay_line: str
    leverage_line: str
    max_loss_line: str
    probability_line: str
    earnings_warning: str | None
    # Figures behind the prose.
    breakeven_price: float | None
    move_required_pct: float | None
    theta_per_day: float | None
    exposure: float | None
    delta: float | None
    implied_volatility: float | None
    iv_estimated: bool
    probability: float | None
    warnings: list[str]


class AccountBook(BaseModel):
    account: AccountOut
    positions: list[PositionOut]
    options: list[OptionOut]
    # Per-account, never summed across accounts.
    total_notional: float
    margin_used: float | None
    exposure_to_margin: float | None
    funding_paid_this_year: float | None
    cost_of_ownership_note: str


class BookOut(BaseModel):
    accounts: list[AccountBook]
    # Stated rather than computed: the absence of a total is the point.
    blended_total_note: str
    unmapped_epics: int
    pending_reconciliation: int
    last_sync: datetime | None


async def _spot_for(session: AsyncSession, ticker: str | None) -> float | None:
    if not ticker:
        return None
    value = (
        await session.execute(
            select(PriceDaily.adjusted_close)
            .where(PriceDaily.ticker == ticker, PriceDaily.adjusted_close.is_not(None))
            .order_by(PriceDaily.date.desc())
            .limit(1)
        )
    ).scalar()
    return float(value) if value is not None else None


async def _next_earnings(session: AsyncSession, ticker: str | None) -> date | None:
    if not ticker:
        return None
    from app import earnings as earnings_module

    row = await earnings_module.next_report(session, ticker)
    return row.report_date if row else None


@router.get("/book")
async def book(
    session: SessionDep,
    horizon_days: Annotated[int, Query(ge=1, le=730)] = DEFAULT_HORIZON_DAYS,
) -> BookOut:
    """Everything IG knows, split by account and never totalled across them."""
    accounts = list(
        (await session.execute(select(IGAccount).order_by(IGAccount.account_id))).scalars()
    )
    epics = {row.epic: row for row in (await session.execute(select(IGEpicMap))).scalars()}
    today = datetime.now(timezone.utc).date()

    books: list[AccountBook] = []
    for account in accounts:
        leveraged = account.regime == "leveraged"

        balance = (
            await session.execute(
                select(IGBalance)
                .where(IGBalance.account_id == account.account_id)
                .order_by(IGBalance.as_of.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        rows = list(
            (
                await session.execute(
                    select(IGPosition).where(
                        IGPosition.account_id == account.account_id,
                        IGPosition.closed_at.is_(None),
                    )
                )
            ).scalars()
        )

        positions: list[PositionOut] = []
        options: list[OptionOut] = []
        total_notional = 0.0

        for row in rows:
            epic = epics.get(row.epic)
            notional = funding_module.notional_of(row)
            if notional is not None:
                total_notional += float(notional)

            funding_paid = funding_per_month = funding_projected = None
            if leveraged and notional is not None and funding_module.is_daily_funded(row.expiry):
                funding_paid = float(await funding_module.paid_to_date(session, row.deal_id))
                funding_per_month = float(
                    funding_module.per_month(
                        notional, settings.ig_benchmark_rate_pct,
                        settings.ig_funding_premium_pct,
                    )
                )
                funding_projected = float(
                    funding_module.project(
                        notional, settings.ig_benchmark_rate_pct,
                        settings.ig_funding_premium_pct, horizon_days,
                    )
                )

            positions.append(PositionOut(
                deal_id=row.deal_id, epic=row.epic,
                ticker=(epic.ticker or epic.underlying_ticker) if epic else None,
                name=epic.instrument_name if epic else None,
                kind=epic.kind if epic else "unknown",
                direction=row.direction, size=float(row.size),
                open_level=float(row.open_level) if row.open_level is not None else None,
                current_level=float(row.current_level) if row.current_level is not None else None,
                currency=row.currency,
                stop_level=float(row.stop_level) if row.stop_level is not None else None,
                notional=float(notional) if notional is not None else None,
                opened_at=row.opened_at,
                needs_mapping=bool(epic and epic.needs_review),
                funding_paid_to_date=funding_paid,
                funding_per_month=funding_per_month,
                funding_projected=funding_projected,
                funding_is_estimate=True,
            ))

        contracts = list(
            (
                await session.execute(
                    select(OptionPosition).where(
                        OptionPosition.account_id == account.account_id,
                        OptionPosition.closed_at.is_(None),
                    )
                )
            ).scalars()
        )
        for contract in contracts:
            mark_row = (
                await session.execute(
                    select(OptionMark)
                    .where(OptionMark.deal_id == contract.deal_id)
                    .order_by(OptionMark.as_of.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            mark = float(mark_row.mark) if mark_row else None
            spot = await _spot_for(session, contract.underlying_ticker)
            view = analyse(
                deal_id=contract.deal_id,
                underlying=contract.underlying_ticker,
                right=contract.right,
                strike=float(contract.strike),
                expiry=contract.expiry,
                contracts=float(contract.contracts),
                multiplier=float(contract.multiplier),
                direction=contract.direction,
                currency=contract.currency or "USD",
                mark=mark,
                spot=spot,
                as_of=today,
                risk_free=settings.ig_option_risk_free_pct / 100.0,
                premium_paid=float(contract.premium) if contract.premium is not None else None,
                next_earnings=await _next_earnings(session, contract.underlying_ticker),
            )
            options.append(OptionOut(
                deal_id=contract.deal_id, underlying=contract.underlying_ticker,
                right=contract.right, strike=float(contract.strike),
                expiry=contract.expiry, days_left=view.days_left,
                contracts=float(contract.contracts),
                multiplier=float(contract.multiplier),
                direction=contract.direction, currency=contract.currency or "USD",
                mark=mark, spot=spot, position_value=view.position_value,
                premium_paid=float(contract.premium) if contract.premium is not None else None,
                breakeven_line=view.breakeven_line, decay_line=view.decay_line,
                leverage_line=view.leverage_line, max_loss_line=view.max_loss_line,
                probability_line=view.probability_line,
                earnings_warning=view.earnings_warning,
                breakeven_price=view.breakeven_price,
                move_required_pct=view.move_required_pct,
                theta_per_day=view.theta_per_day_money,
                exposure=view.exposure, delta=view.delta,
                implied_volatility=view.implied_volatility,
                iv_estimated=view.iv_estimated, probability=view.probability,
                warnings=view.warnings,
            ))

        margin = float(balance.deposit) if balance and balance.deposit is not None else None
        funding_year = (
            float(await funding_module.paid_this_year(
                session, today.year, account_id=account.account_id))
            if leveraged else None
        )

        if leveraged:
            note = (
                "Every night a position is held here, IG charges interest on its FULL "
                "value — not on the margin you put up. That is what makes this vehicle "
                "expensive for holds of a few months, and it is charged whether the "
                "position is winning or losing."
            )
        else:
            note = (
                "Nothing is borrowed in this account, so there is no overnight interest "
                "to pay. Holding for years costs nothing beyond the spread you paid on "
                "the way in."
            )

        books.append(AccountBook(
            account=AccountOut(
                account_id=account.account_id, type=account.type, regime=account.regime,
                label=account.label, currency=account.currency,
                balance=float(balance.balance) if balance and balance.balance is not None else None,
                margin_used=margin,
                available=float(balance.available) if balance and balance.available is not None else None,
                profit_loss=float(balance.profit_loss) if balance and balance.profit_loss is not None else None,
            ),
            positions=positions, options=options,
            total_notional=round(total_notional, 2),
            margin_used=margin,
            exposure_to_margin=(
                round(total_notional / margin, 2) if margin else None
            ),
            funding_paid_this_year=funding_year,
            cost_of_ownership_note=note,
        ))

    unmapped = (
        await session.execute(
            select(func.count()).select_from(IGEpicMap).where(IGEpicMap.needs_review.is_(True))
        )
    ).scalar() or 0
    pending = (
        await session.execute(
            select(func.count()).select_from(IGReconciliation)
            .where(IGReconciliation.status == "pending")
        )
    ).scalar() or 0
    last_seen = (await session.execute(select(func.max(IGPosition.last_seen)))).scalar()

    return BookOut(
        accounts=books,
        blended_total_note=(
            "These accounts are deliberately not added together. A pension and a "
            "leveraged spread bet account are different kinds of money: one cannot "
            "lose more than it holds, the other can, and a single combined figure "
            "would hide exactly that."
        ),
        unmapped_epics=unmapped,
        pending_reconciliation=pending,
        last_sync=last_seen,
    )


class ReconciliationRow(BaseModel):
    id: int
    account_id: str
    kind: str
    deal_id: str | None
    epic: str | None
    ticker: str | None
    prism_stream_id: str | None
    detail: dict
    confidence: float | None
    status: str


@router.get("/reconciliation")
async def reconciliation(session: SessionDep) -> dict:
    """What the first sync proposes. Nothing here has been applied."""
    rows = list(
        (
            await session.execute(
                select(IGReconciliation)
                .where(IGReconciliation.status == "pending")
                .order_by(IGReconciliation.kind, IGReconciliation.id)
            )
        ).scalars()
    )
    return {
        "pending": [
            ReconciliationRow(
                id=row.id, account_id=row.account_id, kind=row.kind,
                deal_id=row.deal_id, epic=row.epic, ticker=row.ticker,
                prism_stream_id=str(row.prism_stream_id) if row.prism_stream_id else None,
                detail=row.detail, confidence=float(row.confidence) if row.confidence else None,
                status=row.status,
            ).model_dump()
            for row in rows
        ],
        "counts": {
            kind: sum(1 for r in rows if r.kind == kind)
            for kind in ("matched", "ig_only", "prism_only")
        },
        "note": (
            "Nothing here has been applied. Accepting a match links the two records "
            "without merging them; accepting an IG-only position imports it and asks "
            "for your thesis; a Prism-only position is never deleted automatically."
        ),
    }


class ResolveRequest(BaseModel):
    accept: bool
    note: str | None = None


@router.post("/reconciliation/{row_id}")
async def resolve(row_id: int, body: ResolveRequest, session: SessionDep) -> dict:
    row = await session.get(IGReconciliation, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no reconciliation row {row_id}")
    row.status = "accepted" if body.accept else "rejected"
    row.resolved_at = datetime.now(timezone.utc)
    if body.note:
        row.detail = {**row.detail, "resolution_note": body.note}
    await session.commit()
    return {"id": row_id, "status": row.status}


class LabelRequest(BaseModel):
    label: str
    regime: str | None = None


@router.post("/accounts/{account_id}/label")
async def label_account(account_id: str, body: LabelRequest, session: SessionDep) -> dict:
    account = await session.get(IGAccount, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail=f"unknown account {account_id}")
    account.label = body.label
    if body.regime in ("leveraged", "unleveraged"):
        # Overridable by hand: IG's account type is a good default, not an
        # authority on how Roger thinks about the money.
        account.regime = body.regime
    await session.commit()
    return {"account_id": account_id, "label": account.label, "regime": account.regime}


class MapRequest(BaseModel):
    ticker: str | None = None
    underlying_ticker: str | None = None


@router.get("/unmapped")
async def unmapped(session: SessionDep) -> list[dict]:
    rows = list(
        (
            await session.execute(
                select(IGEpicMap).where(IGEpicMap.needs_review.is_(True))
                .order_by(IGEpicMap.first_seen)
            )
        ).scalars()
    )
    return [
        {
            "epic": row.epic, "instrument_name": row.instrument_name,
            "kind": row.kind, "instrument_type": row.instrument_type,
            "option_right": row.option_right,
            "option_strike": float(row.option_strike) if row.option_strike else None,
            "option_expiry": row.option_expiry,
            "why": (
                "Prism does not track this company, so there is nothing to link it to."
                if row.kind in ("equity", "option")
                else "Prism does not recognise this kind of instrument."
            ),
        }
        for row in rows
    ]


@router.post("/unmapped/{epic:path}")
async def map_epic(epic: str, body: MapRequest, session: SessionDep) -> dict:
    row = await session.get(IGEpicMap, epic)
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown epic {epic}")
    if body.ticker:
        security = await session.get(Security, body.ticker.upper())
        if security is None:
            raise HTTPException(
                status_code=422,
                detail=f"Prism does not track {body.ticker.upper()} — add it first",
            )
        row.ticker = security.ticker
    if body.underlying_ticker:
        security = await session.get(Security, body.underlying_ticker.upper())
        if security is None:
            raise HTTPException(
                status_code=422,
                detail=f"Prism does not track {body.underlying_ticker.upper()}",
            )
        row.underlying_ticker = security.ticker
    row.needs_review = False
    row.mapped_by = "roger"
    await session.commit()
    return {"epic": epic, "ticker": row.ticker, "underlying_ticker": row.underlying_ticker}
