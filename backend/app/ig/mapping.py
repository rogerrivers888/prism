"""Epic mapping: IG's market identifiers to Prism's securities.

IG identifies markets by epic — an opaque string like
CS.D.MU.CASH.IP or OP.D.MU.160C.IP — not by ticker. Getting this wrong is
uniquely damaging: attach the wrong epic to a ticker and one company's lens
scores appear beside another company's position, silently and permanently.

So nothing is guessed. A mapping is either derived from evidence IG itself
supplies, or the epic is flagged for review and left unmapped. An unmapped
position still syncs and still shows — it simply has no fundamentals attached.
"""

import logging
import re
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.fundamentals import Security
from app.ig.models import IGEpicMap

logger = logging.getLogger(__name__)

# IG's instrument types that Prism understands. Real option positions on
# Roger's account come back as instrumentType "UNKNOWN", so type alone cannot
# be trusted to identify them — see looks_like_option below.
OPTION_TYPES = {"OPT_SHARES", "OPT_INDICES", "OPT_COMMODITIES", "OPT_CURRENCIES",
                "OPT_RATES", "OPT_BONDS"}

# Observed on the live account: "Alphabet Inc - A 35000 CALL", epic
# ON.D.GOOGLub35000I6.CASH.IP, expiry SEP-26, instrumentType UNKNOWN.
OPTION_NAME = re.compile(r"\b(\d+(?:\.\d+)?)\s+(CALL|PUT)\s*$", re.IGNORECASE)

# US equity option strikes and premiums arrive in cents: a 35000 strike on
# Alphabet is $350.00, and a 985 bid is $9.85. Scaling is applied only where
# the quote currency says cents, never guessed from magnitude.
CENTS_CURRENCIES = {"USD"}
EQUITY_TYPES = {"SHARES"}
INDEX_TYPES = {"INDICES"}

MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


@dataclass
class ParsedOption:
    right: str
    strike: float
    expiry: date | None
    underlying_hint: str | None


def parse_expiry(text: str | None) -> date | None:
    """IG expiry strings: 'SEP-26', 'DEC-25', or an ISO date.

    Returns the third Friday of the month for a month-year string, which is
    the standard equity option expiry. Flagged in the caller as approximate:
    a date Prism inferred, not one IG stated.
    """
    if not text or text.strip() in ("-", "DFB"):
        return None
    text = text.strip().upper()
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass
    match = re.match(r"^([A-Z]{3})-(\d{2,4})$", text)
    if not match:
        return None
    month = MONTHS.get(match.group(1))
    if month is None:
        return None
    year = int(match.group(2))
    year += 2000 if year < 100 else 0
    # Third Friday.
    first = date(year, month, 1)
    first_friday = 1 + (4 - first.weekday()) % 7
    return date(year, month, first_friday + 14)


def looks_like_option(
    epic: str, instrument_name: str | None, instrument_type: str | None, expiry: str | None
) -> bool:
    """Is this an option contract?

    IG labels these UNKNOWN rather than OPT_SHARES on Roger's account, so the
    name pattern and a real expiry do the work. Getting this wrong in either
    direction is bad: a missed option is priced as an equity bet, and a false
    positive puts a share position through option maths.
    """
    if (instrument_type or "").upper() in OPTION_TYPES:
        return True
    named = bool(OPTION_NAME.search((instrument_name or "").strip()))
    dated = bool(expiry) and expiry.strip().upper() not in ("-", "DFB")
    return named and dated


def strike_scale(currency: str | None) -> float:
    """Divisor turning IG's quoted strike into the underlying's own units."""
    return 100.0 if (currency or "").upper() in CENTS_CURRENCIES else 1.0


def parse_option_epic(epic: str, instrument_name: str | None) -> ParsedOption | None:
    """Pull right and strike out of an IG option epic or its name.

    IG's option epics vary by market and are not a documented, stable grammar,
    so this reads what it can and returns None when it cannot be sure. The
    name is usually the more reliable source: 'MU 160 CALL SEP-26'.
    """
    name = (instrument_name or "").strip()

    # Preferred source: the instrument name, which IG formats consistently as
    # "<Company> <strike> <CALL|PUT>".
    match = OPTION_NAME.search(name)
    if match:
        strike = float(match.group(1))
        right = match.group(2).lower()
    else:
        # Fallback: the epic's middle segment, e.g. GOOGLub35000I6 — a symbol,
        # two lowercase market letters, the strike, then a series code.
        segments = epic.split(".")
        core = segments[2] if len(segments) > 2 else ""
        fallback = re.match(r"^([A-Z]+)[a-z]{1,3}(\d+)", core)
        if not fallback:
            return None
        strike = float(fallback.group(2))
        upper = f"{name} {epic}".upper()
        if "CALL" in upper:
            right = "call"
        elif "PUT" in upper:
            right = "put"
        else:
            # Neither source states it. Refusing beats a coin flip on whether
            # a position profits from a rise or a fall.
            return None

    expiry = None
    month_year = re.search(r"\b([A-Z]{3})-?(\d{2,4})\b", f"{name} {epic}".upper())
    if month_year and month_year.group(1) in MONTHS:
        expiry = parse_expiry(f"{month_year.group(1)}-{month_year.group(2)}")

    # Underlying symbol: the leading capitals of the epic's middle segment.
    hint = None
    segments = epic.split(".")
    if len(segments) > 2:
        lead = re.match(r"^([A-Z]+)", segments[2])
        if lead:
            hint = lead.group(1)

    return ParsedOption(right=right, strike=strike, expiry=expiry, underlying_hint=hint)


async def resolve_ticker(session: AsyncSession, candidate: str | None) -> str | None:
    """Only returns a ticker Prism actually holds. No fuzzy matching."""
    if not candidate:
        return None
    symbol = candidate.strip().upper().split(".")[0]
    found = (
        await session.execute(select(Security.ticker).where(Security.ticker == symbol))
    ).scalar_one_or_none()
    return found


async def upsert_epic(
    session: AsyncSession,
    epic: str,
    instrument_name: str | None,
    instrument_type: str | None,
    expiry_text: str | None = None,
    currency: str | None = None,
) -> IGEpicMap:
    """Record an epic and map it where the evidence is unambiguous."""
    row = await session.get(IGEpicMap, epic)
    if row is None:
        row = IGEpicMap(
            epic=epic, instrument_name=instrument_name,
            instrument_type=instrument_type, kind="unknown",
            needs_review=True, mapped_by=None,
        )
        session.add(row)
    # A human mapping is never overwritten by the automatic one.
    if row.mapped_by == "roger":
        row.instrument_name = instrument_name or row.instrument_name
        await session.flush()
        return row

    row.instrument_name = instrument_name or row.instrument_name
    row.instrument_type = instrument_type or row.instrument_type

    upper_type = (instrument_type or "").upper()
    if looks_like_option(epic, instrument_name, instrument_type, expiry_text):
        row.kind = "option"
        parsed = parse_option_epic(epic, instrument_name)
        if parsed:
            row.option_right = parsed.right
            row.option_strike = parsed.strike / strike_scale(currency)
            row.option_expiry = parsed.expiry or parse_expiry(expiry_text)
            row.underlying_ticker = await resolve_ticker(session, parsed.underlying_hint)
            row.ticker = row.underlying_ticker
            # Mapped only when every part resolved; a contract missing its
            # strike or underlying is worse than useless in the option maths.
            row.needs_review = not (
                row.option_right and row.option_strike
                and row.option_expiry and row.underlying_ticker
            )
            row.mapped_by = "auto" if not row.needs_review else None
        else:
            row.needs_review = True
    elif upper_type in EQUITY_TYPES:
        row.kind = "equity"
        # IG share epics carry the symbol in the third segment for most
        # markets: CS.D.MU.CASH.IP -> MU. Only accepted when Prism holds it.
        segments = epic.split(".")
        candidate = segments[2] if len(segments) > 2 else None
        ticker = await resolve_ticker(session, candidate)
        if ticker is None and instrument_name:
            ticker = await resolve_ticker(session, instrument_name.split()[0])
        row.ticker = ticker
        row.needs_review = ticker is None
        row.mapped_by = "auto" if ticker else None
    elif upper_type in INDEX_TYPES:
        row.kind = "index"
        # Indices have no security row; nothing to map, nothing to review.
        row.needs_review = False
        row.mapped_by = "auto"
    else:
        row.kind = "other"
        row.needs_review = True

    await session.flush()
    return row


async def unmapped(session: AsyncSession) -> list[IGEpicMap]:
    return list(
        (
            await session.execute(
                select(IGEpicMap).where(IGEpicMap.needs_review.is_(True))
                .order_by(IGEpicMap.first_seen)
            )
        ).scalars()
    )
