"""GBX is not GBP. These tests exist to keep it that way."""

import pytest
from sqlalchemy import select

from app.currency import (
    CurrencyMismatch,
    is_minor_unit,
    major_unit_of,
    require_same_currency,
    same_currency,
)
from app.fundamentals import PriceDaily, Security


def test_gbx_is_not_gbp():
    # A GBX price is one hundredth of a GBP figure. Treating them as the same
    # currency overstates by 100x and looks entirely plausible while doing it.
    assert same_currency("GBX", "GBP") is False
    assert same_currency("GBP", "GBX") is False
    assert same_currency("GBP", "GBP") is True


def test_minor_units_are_recognised_but_not_silently_converted():
    assert is_minor_unit("GBX") is True
    assert is_minor_unit("GBP") is False
    # Knowing the relationship is for explaining the error, not for applying
    # an implicit cast.
    assert major_unit_of("GBX") == "GBP"


def test_combining_gbx_and_gbp_raises_with_an_explanation():
    with pytest.raises(CurrencyMismatch, match="factor of 100"):
        require_same_currency("GBX", "GBP")

    with pytest.raises(CurrencyMismatch):
        require_same_currency("USD", "GBP")

    assert require_same_currency("USD", "USD") == "USD"


def test_no_currency_is_its_own_mismatch():
    with pytest.raises(CurrencyMismatch):
        require_same_currency(None, "GBP")


async def test_quote_currency_is_stored_apart_from_reporting_currency(session):
    """A GBX-quoted security keeps both currencies, and they stay distinct."""
    await session.execute(
        Security.__table__.delete().where(Security.ticker == "VLXTEST")
    )
    session.add(
        Security(
            ticker="VLXTEST",
            name="Volex-like Test plc",
            sector="hardware",
            exchange="LSE",
            currency="GBP",  # accounts are reported in pounds
            quote_currency="GBX",  # but the shares quote in pence
        )
    )
    session.add(
        PriceDaily(
            ticker="VLXTEST",
            date=__import__("datetime").date(2026, 8, 10),
            close=350.0,
            adjusted_close=350.0,
            currency="GBX",
        )
    )
    await session.flush()

    security = await session.get(Security, "VLXTEST")
    assert security.currency == "GBP"
    assert security.quote_currency == "GBX"
    assert not same_currency(security.currency, security.quote_currency)

    # The price row carries the quote currency, not the reporting one, so a
    # consumer cannot pick up 350 and read it as £350.
    price = (
        await session.execute(
            select(PriceDaily).where(PriceDaily.ticker == "VLXTEST")
        )
    ).scalar_one()
    assert price.currency == "GBX"
    with pytest.raises(CurrencyMismatch):
        require_same_currency(price.currency, security.currency)

    await session.rollback()
