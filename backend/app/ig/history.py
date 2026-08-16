"""IG transaction history: real fills, and the funding IG actually charged.

Two things matter here that the positions feed cannot give:

  1. What Roger PAID. The positions endpoint returns openLevel as null on
     every one of his positions, so true breakeven on an option is
     unobtainable without this. A breakeven computed from today's mark
     answers "what if I opened it now", which is a different question.

  2. What IG CHARGED. Funding appears as interest transactions, so the
     "paid to IG this year" figure can be a fact rather than a model.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.events.store import append
from app.ig.client import IGClient
from app.ig.models import (
    FundingAccrual,
    IGAccount,
    IGClosedTrade,
    IGPosition,
    OptionPosition,
)
from app.ingest import archive as archive_module

logger = logging.getLogger(__name__)

# IG labels its financing charges in the transaction description.
INTEREST_MARKERS = ("INTEREST", "FUNDING", "OVERNIGHT")

# "£-0.32", "E-12.34", "$45.00" -> Decimal
_NUMERIC = re.compile(r"-?\d+(?:[.,]\d+)?")


def parse_amount(value: str | None) -> Decimal | None:
    if value in (None, "", "-"):
        return None
    match = _NUMERIC.search(str(value).replace(",", ""))
    if not match:
        return None
    try:
        return Decimal(match.group(0))
    except InvalidOperation:
        return None


def is_interest(entry: dict) -> bool:
    """Is this transaction a financing charge rather than a trade?"""
    name = (entry.get("instrumentName") or "").upper()
    kind = (entry.get("transactionType") or "").upper()
    return kind == "WITH" and any(marker in name for marker in INTEREST_MARKERS)


@dataclass
class HistoryReport:
    transactions: int = 0
    interest_charges: int = 0
    interest_total: Decimal = Decimal(0)
    premiums_resolved: int = 0
    deals_linked: int = 0
    closed_trades: int = 0
    entry_levels_filled: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "transactions": self.transactions,
            "interest_charges": self.interest_charges,
            "interest_total": str(self.interest_total),
            "premiums_resolved": self.premiums_resolved,
            "deals_linked": self.deals_linked,
            "closed_trades": self.closed_trades,
            "entry_levels_filled": self.entry_levels_filled,
            "errors": self.errors,
        }


def _timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(str(value)[:19], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


async def sync_history(
    session: AsyncSession,
    client: IGClient,
    account: IGAccount,
    since: date,
    report: HistoryReport,
) -> list[dict]:
    """Pull transactions and activities, archive both, then interpret.

    Returns the activity list, which carries IG's dealId linkage.
    """
    today = datetime.now(timezone.utc).date()

    transactions = await client.transactions(
        account.account_id, since.isoformat(), today.isoformat()
    )
    await archive_module.archive(
        session, client.name, "transactions", account.account_id, transactions
    )

    from app.ig.sync import _account_stream

    for entry in transactions.get("transactions", []):
        reference = entry.get("reference")
        if not reference:
            continue
        occurred = _timestamp(entry.get("dateUtc") or entry.get("date")) or datetime.now(
            timezone.utc
        )
        profit = parse_amount(entry.get("profitAndLoss"))

        await append(
            session,
            stream_id=_account_stream(account.account_id),
            stream_type="ig_account",
            event_type="IGTradeDetected",
            payload={
                "account_id": account.account_id,
                "reference": reference,
                "instrument_name": entry.get("instrumentName"),
                "transaction_type": entry.get("transactionType"),
                "size": str(parse_amount(entry.get("size")) or "") or None,
                "open_level": str(parse_amount(entry.get("openLevel")) or "") or None,
                "close_level": str(parse_amount(entry.get("closeLevel")) or "") or None,
                "profit_loss": str(profit) if profit is not None else None,
                "currency": entry.get("currency"),
                "cash_transaction": bool(entry.get("cashTransaction")),
            },
            occurred_at=occurred,
            actor="ig-history",
        )
        report.transactions += 1

        # A DEAL with both an open and a close level is a completed trade.
        # These are the only record of history: the positions feed reports
        # what is live and nothing else.
        if (entry.get("transactionType") or "").upper() == "DEAL":
            await _record_closed_trade(session, account, entry, occurred, profit, report)

        # IG's own funding charge. Recorded against the account rather than a
        # deal, because IG aggregates interest per instrument per night and
        # does not attribute it to a dealId.
        if is_interest(entry) and profit is not None:
            report.interest_charges += 1
            report.interest_total += abs(profit)
            await session.execute(
                pg_insert(FundingAccrual)
                .values(
                    # Account-level actuals share a synthetic deal key so they
                    # never collide with per-position estimates.
                    deal_id=f"ACTUAL:{account.account_id}:{entry.get('instrumentName','')[:40]}",
                    as_of=occurred.date(),
                    notional=Decimal(0),
                    annual_rate_pct=Decimal(0),
                    charge=abs(profit),
                    currency=entry.get("currency"),
                    estimated=False,
                )
                .on_conflict_do_update(
                    constraint="pk_funding_accruals",
                    set_={"charge": abs(profit), "estimated": False},
                )
            )

    # Activities carry dealId and epic, which is how an opening level gets
    # attached to the position it belongs to.
    activities = await client.activity(
        account.account_id, f"{since.isoformat()}T00:00:00"
    )
    await archive_module.archive(
        session, client.name, "activity", account.account_id, activities
    )
    await session.flush()
    # Returned so premiums can be resolved against IG's own dealId linkage.
    return activities.get("activities", [])


async def _record_closed_trade(
    session: AsyncSession, account: IGAccount, entry: dict,
    closed_at: datetime, profit: Decimal | None, report: HistoryReport,
) -> None:
    """Project one historical trade, matching it to a ticker where possible."""
    from app.ig.mapping import OPTION_NAME, strike_scale
    from app.fundamentals import Security

    open_level = parse_amount(entry.get("openLevel"))
    close_level = parse_amount(entry.get("closeLevel"))
    if open_level is None and close_level is None:
        return

    name = (entry.get("instrumentName") or "").strip()
    currency = entry.get("currency")

    # Options carry their right and strike in the name.
    right = strike = None
    match = OPTION_NAME.search(name)
    if match:
        strike = Decimal(match.group(1)) / Decimal(str(strike_scale(currency)))
        right = match.group(2).lower()

    # Only a ticker Prism actually holds; never a guess.
    ticker = None
    lead = name.split()[0].upper() if name else ""
    if len(lead) >= 2:
        found = (
            await session.execute(select(Security.ticker).where(Security.ticker == lead))
        ).scalar_one_or_none()
        ticker = found

    opened_at = _timestamp(entry.get("openDateUtc"))
    days = (closed_at.date() - opened_at.date()).days if opened_at else None
    size = parse_amount(entry.get("size"))

    await session.execute(
        pg_insert(IGClosedTrade)
        .values(
            reference=entry["reference"], account_id=account.account_id,
            instrument_name=name or None, ticker=ticker,
            kind="option" if right else "equity",
            direction="long" if (size or Decimal(0)) >= 0 else "short",
            size=abs(size) if size is not None else None,
            open_level=open_level, close_level=close_level,
            profit_loss=profit, currency=currency,
            opened_at=opened_at, closed_at=closed_at, days_held=days,
            option_right=right, option_strike=strike,
        )
        .on_conflict_do_update(
            index_elements=["reference"],
            set_={"profit_loss": profit, "close_level": close_level, "ticker": ticker},
        )
    )
    report.closed_trades += 1


async def resolve_premiums(
    session: AsyncSession,
    report: HistoryReport,
    activities: list[dict] | None = None,
) -> None:
    """Fill in what each option actually cost, keyed on the deal itself.

    The positions feed returns openLevel as null on every one of Roger's
    positions, so without this a breakeven is computed from today's mark —
    which answers "what if I opened this now", a different question.

    Matched on IG's own affectedDealId rather than on instrument names. Name
    matching was tried and was actively harmful: "Alphabet Inc - A 35000 CALL"
    and "...36500 CALL" share seventeen characters, so a prefix match attached
    one contract's premium to another and silently corrupted its breakeven.
    Where no opening activity is found the premium stays None and the screen
    says which price it is using instead.
    """
    from app.ig.mapping import strike_scale

    options = list(
        (
            await session.execute(
                select(OptionPosition).where(OptionPosition.closed_at.is_(None))
            )
        ).scalars()
    )
    if not options or not activities:
        return

    # dealId -> opening level, from IG's own linkage.
    levels: dict[str, Decimal] = {}
    for activity in activities:
        details = activity.get("details") or {}
        level = details.get("level")
        if level is None:
            continue
        for action in details.get("actions") or []:
            deal_id = action.get("affectedDealId")
            if deal_id and (action.get("actionType") or "").upper().startswith("POSITION_OPEN"):
                amount = parse_amount(str(level))
                if amount is not None:
                    levels[deal_id] = amount

    # IG returns openLevel as null on the positions feed, so without this
    # every open position shows no profit or loss at all. The activity feed
    # has the real fill level, keyed on the deal.
    for deal_id, level in levels.items():
        position = await session.get(IGPosition, deal_id)
        if position is not None and position.open_level is None:
            position.open_level = level
            report.entry_levels_filled += 1

    for option in options:
        level = levels.get(option.deal_id)
        if level is None:
            continue
        scale = Decimal(str(strike_scale(option.currency)))
        option.premium = (
            level / scale
            * abs(Decimal(str(option.contracts)))
            * Decimal(str(option.multiplier))
        )
        report.premiums_resolved += 1

    await session.flush()
