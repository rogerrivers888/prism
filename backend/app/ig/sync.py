"""IG sync. Observes, archives, records events. Never trades, never deletes.

Order of operations per run, and the reason for it:
  1. Login once, list accounts, classify each into a risk regime.
  2. Per account: fetch positions, archive the raw payload, then parse it.
  3. Record every observation as an event; project into read models.
  4. Positions that vanished from the feed are marked closed with an event —
     never deleted, because "IG stopped reporting it" is an observation about
     IG, not proof of what happened to the trade.

Nothing here writes into Prism's own positions table. Linking the two is
reconciliation's job, and it is reviewed rather than applied automatically.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.events.store import append
from app.ig import mapping as mapping_module
from app.ig.client import IGClient
from app.ig.models import (
    IGAccount,
    IGBalance,
    IGEpicMap,
    IGPosition,
    OptionMark,
    OptionPosition,
)
from app.ingest import archive as archive_module

logger = logging.getLogger(__name__)

# IG account types that are leveraged and funded nightly.
LEVERAGED_TYPES = {"SPREADBET", "CFD"}


def regime_for(account_type: str | None) -> str:
    """Which risk regime an account belongs to.

    A pension and a spread bet book are opposite regimes and must never be
    totalled together, so this decision is made once, at the source, and
    carried everywhere downstream.
    """
    return "leveraged" if (account_type or "").upper() in LEVERAGED_TYPES else "unleveraged"


def _as_str(value) -> str | None:
    """Decimal-or-None to a JSON-safe string.

    IG omits openLevel on several live positions, and an absent number must
    travel as null rather than as an empty string — the payload validator
    rejects "" and would fail the whole sync on one missing field.
    """
    decimal = _decimal(value)
    return str(decimal) if decimal is not None else None


def _decimal(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _timestamp(value: str | None) -> datetime | None:
    """IG timestamps come in several shapes; unparseable means unknown."""
    if not value:
        return None
    text = value.strip().replace("/", "-")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(text[:26], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


@dataclass
class SyncReport:
    accounts: int = 0
    positions_seen: int = 0
    positions_closed: int = 0
    options_seen: int = 0
    balances: int = 0
    transactions: int = 0
    epics_needing_review: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return dict(self.__dict__)


async def sync_accounts(session: AsyncSession, client: IGClient) -> list[IGAccount]:
    """List every account under the login and classify it."""
    payload = await client.accounts()
    await archive_module.archive(session, client.name, "accounts", None, payload)

    rows: list[IGAccount] = []
    for entry in payload.get("accounts", []):
        account_id = entry.get("accountId")
        if not account_id:
            continue
        row = await session.get(IGAccount, account_id)
        if row is None:
            row = IGAccount(
                account_id=account_id,
                type=entry.get("accountType", "UNKNOWN"),
                regime=regime_for(entry.get("accountType")),
                # A sensible default label; Roger renames it in the UI and
                # his name is never overwritten by a later sync.
                label=entry.get("accountName"),
                currency=entry.get("currency"),
                is_preferred=bool(entry.get("preferred")),
                first_seen=datetime.now(timezone.utc),
            )
            session.add(row)
        else:
            row.type = entry.get("accountType", row.type)
            row.regime = regime_for(entry.get("accountType"))
            row.currency = entry.get("currency") or row.currency
            row.is_preferred = bool(entry.get("preferred"))
        rows.append(row)

        balance = entry.get("balance") or {}
        if balance:
            today = datetime.now(timezone.utc).date()
            await session.execute(
                pg_insert(IGBalance)
                .values(
                    account_id=account_id, as_of=today,
                    balance=_decimal(balance.get("balance")),
                    deposit=_decimal(balance.get("deposit")),
                    profit_loss=_decimal(balance.get("profitLoss")),
                    available=_decimal(balance.get("available")),
                )
                .on_conflict_do_update(
                    constraint="pk_ig_balances",
                    set_={
                        "balance": _decimal(balance.get("balance")),
                        "deposit": _decimal(balance.get("deposit")),
                        "profit_loss": _decimal(balance.get("profitLoss")),
                        "available": _decimal(balance.get("available")),
                    },
                )
            )
            await append(
                session,
                stream_id=_account_stream(account_id),
                stream_type="ig_account",
                event_type="IGBalanceObserved",
                payload={
                    "account_id": account_id,
                    "balance": _as_str(balance.get("balance")),
                    "deposit": _as_str(balance.get("deposit")),
                    "profit_loss": _as_str(balance.get("profitLoss")),
                    "available": _as_str(balance.get("available")),
                    "currency": entry.get("currency"),
                },
                occurred_at=datetime.now(timezone.utc),
                actor="ig-sync",
            )
    await session.flush()
    return rows


import uuid

# Stable per-account and per-deal stream ids, so an event stream is
# reconstructable from the IG identifier alone.
_NAMESPACE = uuid.UUID("3f2b6a1e-9c5d-4a7b-8e10-1f2a3b4c5d6e")


def _account_stream(account_id: str) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, f"account:{account_id}")


def _deal_stream(deal_id: str) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, f"deal:{deal_id}")


async def sync_positions(
    session: AsyncSession, client: IGClient, account: IGAccount, report: SyncReport
) -> None:
    """Open positions for one account, archived then parsed."""
    payload = await client.positions(account.account_id)
    await archive_module.archive(
        session, client.name, "positions", account.account_id, payload
    )

    now = datetime.now(timezone.utc)
    seen: set[str] = set()

    for entry in payload.get("positions", []):
        position = entry.get("position") or {}
        market = entry.get("market") or {}
        deal_id = position.get("dealId")
        epic = market.get("epic")
        if not deal_id or not epic:
            logger.warning("ig position with no dealId or epic, skipping")
            continue
        seen.add(deal_id)

        epic_row = await mapping_module.upsert_epic(
            session,
            epic=epic,
            instrument_name=market.get("instrumentName"),
            instrument_type=market.get("instrumentType"),
            expiry_text=market.get("expiry"),
            currency=position.get("currency"),
        )

        size = _decimal(position.get("size")) or Decimal(0)
        direction = (position.get("direction") or "BUY").upper()
        # IG quotes bid/offer; the mark for a long is the bid.
        current = _decimal(market.get("bid") if direction == "BUY" else market.get("offer"))

        event = await append(
            session,
            stream_id=_deal_stream(deal_id),
            stream_type="ig_deal",
            event_type="IGPositionObserved",
            payload={
                "account_id": account.account_id,
                "deal_id": deal_id,
                "epic": epic,
                "direction": direction,
                "size": str(size),
                "open_level": _as_str(position.get("openLevel")),
                "current_level": str(current) if current is not None else None,
                "currency": position.get("currency"),
                "stop_level": _as_str(position.get("stopLevel")),
                "limit_level": _as_str(position.get("limitLevel")),
                "contract_size": _as_str(position.get("contractSize")),
                "instrument_type": market.get("instrumentType"),
                "instrument_name": market.get("instrumentName"),
                "expiry": market.get("expiry"),
            },
            # IG's own timestamp for when the position was created, falling
            # back to now only when it gives none.
            occurred_at=_timestamp(position.get("createdDateUTC")
                                   or position.get("createdDate")) or now,
            actor="ig-sync",
        )

        row = await session.get(IGPosition, deal_id)
        values = dict(
            account_id=account.account_id, epic=epic, direction=direction, size=size,
            open_level=_decimal(position.get("openLevel")),
            current_level=current,
            currency=position.get("currency"),
            stop_level=_decimal(position.get("stopLevel")),
            limit_level=_decimal(position.get("limitLevel")),
            contract_size=_decimal(position.get("contractSize")),
            opened_at=_timestamp(position.get("createdDateUTC") or position.get("createdDate")),
            expiry=market.get("expiry"),
            instrument_type=market.get("instrumentType"),
            last_seen=now, closed_at=None, last_event_id=event.id,
        )
        if row is None:
            session.add(IGPosition(deal_id=deal_id, **values))
        else:
            for key, value in values.items():
                setattr(row, key, value)
        report.positions_seen += 1

        if epic_row.kind == "option":
            await _record_option(session, account, epic_row, position, market, deal_id, now, report)

    # Anything previously open and now absent is closed — with an event.
    previously_open = (
        await session.execute(
            select(IGPosition).where(
                IGPosition.account_id == account.account_id,
                IGPosition.closed_at.is_(None),
            )
        )
    ).scalars()
    for row in previously_open:
        if row.deal_id in seen:
            continue
        row.closed_at = now
        await append(
            session,
            stream_id=_deal_stream(row.deal_id),
            stream_type="ig_deal",
            event_type="IGPositionClosed",
            payload={
                "account_id": account.account_id,
                "deal_id": row.deal_id,
                "last_seen": row.last_seen.isoformat(),
            },
            occurred_at=now,
            actor="ig-sync",
        )
        option = await session.get(OptionPosition, row.deal_id)
        if option is not None:
            option.closed_at = now
        report.positions_closed += 1

    await session.flush()


async def _record_option(
    session, account, epic_row: IGEpicMap, position, market, deal_id, now, report
) -> None:
    """Resolve an option contract and store today's mark.

    Deliberately conservative: without a strike, expiry and right the contract
    is left in ig_positions only, flagged for review. Half-parsing an option
    into the option model would produce confident nonsense in the four
    plain-English lines that depend on it.
    """
    if not (epic_row.option_right and epic_row.option_strike and epic_row.option_expiry):
        report.epics_needing_review += 1
        return

    contracts = _decimal(position.get("size")) or Decimal(0)
    direction = "long" if (position.get("direction") or "BUY").upper() == "BUY" else "short"
    multiplier = _decimal(position.get("contractSize")) or Decimal(100)
    open_level = _decimal(position.get("openLevel"))
    currency = position.get("currency")

    row = await session.get(OptionPosition, deal_id)
    if row is None:
        row = OptionPosition(
            deal_id=deal_id, account_id=account.account_id, epic=epic_row.epic,
            underlying_ticker=epic_row.underlying_ticker,
            right=epic_row.option_right, strike=epic_row.option_strike,
            expiry=epic_row.option_expiry, contracts=contracts, direction=direction,
            multiplier=multiplier,
            premium=(open_level * contracts * multiplier) if open_level else None,
            currency=currency,
            opened_at=_timestamp(position.get("createdDateUTC") or position.get("createdDate")),
            iv_at_entry=None, iv_estimated=True, closed_at=None, last_seen=now,
        )
        session.add(row)
    else:
        row.contracts = contracts
        row.underlying_ticker = epic_row.underlying_ticker or row.underlying_ticker
        row.last_seen = now
        row.closed_at = None

    # Today's mark, from IG's own quote. Greeks are computed later by the
    # analytics layer, which needs the underlying price.
    bid = _decimal(market.get("bid"))
    offer = _decimal(market.get("offer"))
    mark = bid if direction == "long" else offer
    if mark is None:
        mark = bid or offer
    if mark is not None:
        await session.execute(
            pg_insert(OptionMark)
            .values(deal_id=deal_id, as_of=now.date(), mark=mark,
                    iv_estimated=True)
            .on_conflict_do_update(
                constraint="pk_option_marks", set_={"mark": mark}
            )
        )
    report.options_seen += 1


async def sync_transactions(
    session: AsyncSession, client: IGClient, account: IGAccount,
    from_date: date, report: SyncReport,
) -> None:
    """Transaction history as far back as IG provides."""
    today = datetime.now(timezone.utc).date()
    payload = await client.transactions(
        account.account_id, from_date.isoformat(), today.isoformat()
    )
    await archive_module.archive(
        session, client.name, "transactions", account.account_id, payload
    )

    for entry in payload.get("transactions", []):
        reference = entry.get("reference")
        if not reference:
            continue
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
                "size": entry.get("size"),
                "open_level": entry.get("openLevel"),
                "close_level": entry.get("closeLevel"),
                "profit_loss": _strip_currency(entry.get("profitAndLoss")),
                "currency": entry.get("currency"),
                "cash_transaction": bool(entry.get("cashTransaction")),
            },
            occurred_at=_timestamp(entry.get("dateUtc") or entry.get("date"))
            or datetime.now(timezone.utc),
            actor="ig-sync",
        )
        report.transactions += 1
    await session.flush()


def _strip_currency(value: str | None) -> str | None:
    """IG returns P&L as strings like 'E-12.34' or '£45.00'."""
    if not value:
        return None
    cleaned = "".join(c for c in str(value) if c.isdigit() or c in ".-")
    return cleaned or None
