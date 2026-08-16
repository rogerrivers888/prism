"""Overnight funding on leveraged positions — the cost nobody sees.

IG charges funding on the FULL value of a spread bet position every night it
is held, not on the margin actually put up. That distinction is the whole
point of this module: a £31,000 exposure held on £5,900 of margin is charged
on £31,000, and over a three or four month hold the total is large enough to
decide whether the trade was worth doing at all.

Two sources, and the distinction is kept visible:

  ACTUAL   — IG bills interest as transactions ("Long Interest for US/Can
             shares"), which the history sync captures. Where these exist
             they are the truth and Prism uses them.
  ESTIMATE — Prism's own calculation from IG's published formula,
             (notional x (benchmark + premium) / 365) per night. Used for
             positions IG has not yet billed, and for the only question that
             cannot be answered from history: what will holding this for
             another three months cost?

Estimates are labelled as such everywhere they surface. A projection is a
guess about the future and must never be shown as a charge.

Nothing here applies to the pension: an unleveraged account borrows nothing
and is charged nothing, and showing a funding column against it would invent
a cost that does not exist.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.events.store import append
from app.ig.models import FundingAccrual, IGAccount, IGPosition

logger = logging.getLogger(__name__)

# IG does not charge funding on dated products — the cost is already in the
# forward price. Only daily-funded bets accrue.
DAILY_FUNDED_EXPIRIES = {"-", "DFB", "DAILY FUNDED BET", ""}


def is_daily_funded(expiry: str | None) -> bool:
    return (expiry or "-").strip().upper() in DAILY_FUNDED_EXPIRIES


def notional_of(position: IGPosition) -> Decimal | None:
    """Full position value: size x price. Not margin.

    Uses the current level where IG gives one, falling back to the opening
    level. Without either there is no honest number and None is returned.
    """
    level = position.current_level or position.open_level
    if level is None:
        return None
    return abs(Decimal(str(position.size)) * Decimal(str(level)))


def nightly_charge(
    notional: Decimal, benchmark_pct: float, premium_pct: float
) -> tuple[Decimal, Decimal]:
    """One night's funding, and the annual rate it came from.

    Long positions pay benchmark + premium. Short positions in principle
    receive benchmark - premium, which at current rates is still a payment;
    Prism charges the long formula either way and says so, because getting a
    credit wrong in Roger's favour is the more dangerous error.
    """
    annual = Decimal(str(benchmark_pct)) + Decimal(str(premium_pct))
    charge = notional * annual / Decimal(100) / Decimal(365)
    return charge.quantize(Decimal("0.0001")), annual


@dataclass
class FundingReport:
    positions_charged: int = 0
    total_charge: Decimal = Decimal(0)
    skipped_no_price: int = 0
    skipped_not_funded: int = 0

    def as_dict(self) -> dict:
        return {
            "positions_charged": self.positions_charged,
            "total_charge": str(self.total_charge),
            "skipped_no_price": self.skipped_no_price,
            "skipped_not_funded": self.skipped_not_funded,
        }


async def accrue(
    session: AsyncSession,
    as_of: date,
    benchmark_pct: float,
    premium_pct: float,
) -> FundingReport:
    """Charge one night's funding against every open leveraged position.

    Idempotent per (deal, date): re-running a night overwrites rather than
    double-charging, which matters because the nightly job is designed to be
    safe to retry.
    """
    report = FundingReport()

    leveraged = {
        row.account_id
        for row in (
            await session.execute(
                select(IGAccount).where(IGAccount.regime == "leveraged")
            )
        ).scalars()
    }
    if not leveraged:
        return report

    positions = (
        await session.execute(
            select(IGPosition).where(
                IGPosition.closed_at.is_(None),
                IGPosition.account_id.in_(leveraged),
            )
        )
    ).scalars()

    for position in positions:
        if not is_daily_funded(position.expiry):
            # Dated products and options carry their financing in the price.
            report.skipped_not_funded += 1
            continue
        notional = notional_of(position)
        if notional is None:
            report.skipped_no_price += 1
            continue

        charge, annual = nightly_charge(notional, benchmark_pct, premium_pct)
        await session.execute(
            pg_insert(FundingAccrual)
            .values(
                deal_id=position.deal_id, as_of=as_of, notional=notional,
                annual_rate_pct=annual, charge=charge,
                currency=position.currency, estimated=True,
            )
            .on_conflict_do_update(
                constraint="pk_funding_accruals",
                set_={"notional": notional, "annual_rate_pct": annual,
                      "charge": charge},
            )
        )
        await append(
            session,
            stream_id=_deal_stream(position.deal_id),
            stream_type="ig_deal",
            event_type="FundingCharged",
            payload={
                "account_id": position.account_id,
                "deal_id": position.deal_id,
                "as_of": as_of.isoformat(),
                "notional": str(notional),
                "annual_rate_pct": str(annual),
                "charge": str(charge),
                "currency": position.currency,
                "estimated": True,
            },
            occurred_at=datetime.combine(as_of, datetime.min.time(), tzinfo=timezone.utc),
            actor="ig-funding",
        )
        report.positions_charged += 1
        report.total_charge += charge

    await session.flush()
    return report


from app.ig.sync import _deal_stream  # noqa: E402  (shared stream identity)


async def paid_to_date(session: AsyncSession, deal_id: str) -> Decimal:
    total = (
        await session.execute(
            select(func.coalesce(func.sum(FundingAccrual.charge), 0)).where(
                FundingAccrual.deal_id == deal_id
            )
        )
    ).scalar()
    return Decimal(str(total or 0))


async def paid_this_year(
    session: AsyncSession, year: int, account_id: str | None = None
) -> Decimal:
    """Funding paid, optionally for one account.

    Scoping matters: the two accounts are different regimes and a figure that
    silently totals both would attribute the spread bet book's financing to
    the account that borrowed nothing.
    """
    query = select(func.coalesce(func.sum(FundingAccrual.charge), 0)).where(
        FundingAccrual.as_of >= date(year, 1, 1),
        FundingAccrual.as_of <= date(year, 12, 31),
    )
    if account_id:
        # Estimates key on the deal; IG's actual charges key on a synthetic
        # ACTUAL:<account>:<instrument> id. Both are matched here.
        deals = select(IGPosition.deal_id).where(IGPosition.account_id == account_id)
        query = query.where(
            FundingAccrual.deal_id.in_(deals)
            | FundingAccrual.deal_id.like(f"ACTUAL:{account_id}:%")
        )
    total = (await session.execute(query)).scalar()
    return Decimal(str(total or 0))


def project(
    notional: Decimal, benchmark_pct: float, premium_pct: float, days: int
) -> Decimal:
    """What holding this position for another N days will cost.

    The figure that answers Roger's actual question: he plans three to four
    month leveraged holds, and this says what the financing alone will take
    out of the trade before it has to be right about anything.
    """
    charge, _ = nightly_charge(notional, benchmark_pct, premium_pct)
    return (charge * Decimal(days)).quantize(Decimal("0.01"))


def per_month(notional: Decimal, benchmark_pct: float, premium_pct: float) -> Decimal:
    return project(notional, benchmark_pct, premium_pct, 30)
