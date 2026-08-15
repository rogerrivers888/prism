"""Epic mapping against the shapes IG actually returns for Roger's account.

Every fixture here was copied from a live response, because the documented
shapes and the real ones differ in ways that matter: options come back with
instrumentType UNKNOWN and strikes quoted in cents.
"""

from datetime import date

import pytest
from sqlalchemy import select

from app.fundamentals import Security
from app.ig.mapping import (
    looks_like_option,
    parse_expiry,
    parse_option_epic,
    strike_scale,
    upsert_epic,
)
from app.ig.models import IGEpicMap

# Verbatim from the live account.
LIVE = [
    ("ON.D.GOOGLub35000I6.CASH.IP", "Alphabet Inc - A 35000 CALL", "UNKNOWN", "SEP-26"),
    ("ON.D.NVDAuc22000I6.CASH.IP", "NVIDIA Corp 22000 CALL", "UNKNOWN", "SEP-26"),
    ("ON.D.AMDsa54000I6.CASH.IP", "Advanced Micro Devices Inc 54000 CALL", "UNKNOWN", "SEP-26"),
    ("ON.D.SPCXUSud13000I6.CASH.IP", "SpaceX (24 Hours) 13000 CALL", "UNKNOWN", "SEP-26"),
    ("UD.D.STRLUS.DAILY.IP", "Sterling Infrastructure Inc", "SHARES", "DFB"),
]


def test_options_are_detected_despite_type_unknown():
    """IG labels these UNKNOWN. Relying on instrumentType would have priced
    every one of Roger's contracts as an equity bet."""
    for epic, name, typ, expiry in LIVE[:4]:
        assert looks_like_option(epic, name, typ, expiry), name
    epic, name, typ, expiry = LIVE[4]
    assert not looks_like_option(epic, name, typ, expiry), "a daily funded share bet is not an option"


def test_a_share_position_is_never_mistaken_for_an_option():
    assert not looks_like_option("UD.D.STRLUS.DAILY.IP", "Sterling Infrastructure Inc",
                                 "SHARES", "DFB")
    # A name with a number but no CALL/PUT and no expiry must not qualify.
    assert not looks_like_option("CS.D.MU.CASH.IP", "Micron Technology 3", "SHARES", "-")


def test_strike_and_right_come_out_of_the_name():
    parsed = parse_option_epic("ON.D.GOOGLub35000I6.CASH.IP", "Alphabet Inc - A 35000 CALL")
    assert parsed.right == "call"
    assert parsed.strike == 35000
    assert parsed.underlying_hint == "GOOGL"


def test_us_strikes_are_in_cents():
    """A 35000 strike on Alphabet is $350, not $35,000. Getting this wrong
    makes every breakeven and probability meaningless."""
    assert strike_scale("USD") == 100.0
    assert strike_scale("GBP") == 1.0
    assert 35000 / strike_scale("USD") == 350.0


def test_the_epic_is_a_fallback_when_the_name_is_unhelpful():
    parsed = parse_option_epic("ON.D.NVDAuc22000I6.CASH.IP", "NVIDIA Corp CALL")
    assert parsed.strike == 22000
    assert parsed.underlying_hint == "NVDA"


def test_a_contract_with_no_stated_right_is_refused():
    """Guessing call vs put decides whether a position profits from a rise or
    a fall. Refusing is the only safe answer."""
    assert parse_option_epic("ON.D.XYZab12345I6.CASH.IP", "Something Inc") is None


def test_expiry_parsing():
    assert parse_expiry("SEP-26") == date(2026, 9, 18)  # third Friday
    assert parse_expiry("2026-09-19") == date(2026, 9, 19)
    assert parse_expiry("DFB") is None
    assert parse_expiry("-") is None
    assert parse_expiry(None) is None


@pytest.mark.asyncio
async def test_upsert_resolves_a_full_option_when_the_underlying_is_held(session):
    session.add(Security(ticker="NVDA", name="NVIDIA Corp", sector="semiconductors",
                         currency="USD", quote_currency="USD", is_active=True))
    await session.flush()

    row = await upsert_epic(
        session, epic="ON.D.NVDAuc22000I6.CASH.IP",
        instrument_name="NVIDIA Corp 22000 CALL",
        instrument_type="UNKNOWN", expiry_text="SEP-26", currency="USD",
    )
    assert row.kind == "option"
    assert row.option_right == "call"
    assert float(row.option_strike) == 220.0
    assert row.option_expiry == date(2026, 9, 18)
    assert row.underlying_ticker == "NVDA"
    assert row.needs_review is False


@pytest.mark.asyncio
async def test_an_unlistable_underlying_is_flagged_not_guessed(session):
    """SpaceX is not a listed equity. The contract still syncs; it simply has
    no fundamentals attached, and says so."""
    row = await upsert_epic(
        session, epic="ON.D.SPCXUSud13000I6.CASH.IP",
        instrument_name="SpaceX (24 Hours) 13000 CALL",
        instrument_type="UNKNOWN", expiry_text="SEP-26", currency="USD",
    )
    assert row.kind == "option"
    assert row.underlying_ticker is None
    assert row.needs_review is True


@pytest.mark.asyncio
async def test_a_human_mapping_is_never_overwritten(session):
    row = await upsert_epic(session, epic="ON.D.WEIRD.CASH.IP",
                            instrument_name="Odd 100 CALL",
                            instrument_type="UNKNOWN", expiry_text="SEP-26")
    row.ticker = "MU"
    row.underlying_ticker = "MU"
    row.needs_review = False
    row.mapped_by = "roger"
    await session.flush()

    await upsert_epic(session, epic="ON.D.WEIRD.CASH.IP",
                      instrument_name="Odd 100 CALL",
                      instrument_type="UNKNOWN", expiry_text="SEP-26")
    refreshed = await session.get(IGEpicMap, "ON.D.WEIRD.CASH.IP")
    assert refreshed.mapped_by == "roger"
    assert refreshed.underlying_ticker == "MU"
