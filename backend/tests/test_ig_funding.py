"""Funding: charged on the full value, only where it is actually charged."""

from datetime import date
from decimal import Decimal

import pytest

from app.ig.funding import (
    is_daily_funded,
    nightly_charge,
    notional_of,
    per_month,
    project,
)
from app.ig.models import IGPosition


def position(**kw):
    base = dict(deal_id="D", account_id="A", epic="E", direction="BUY",
                size=Decimal("0.03"), current_level=Decimal("57648"),
                last_seen=date(2026, 8, 16), last_event_id=1, expiry="DFB")
    base.update(kw)
    return IGPosition(**base)


def test_notional_is_the_full_value_not_the_margin():
    """The entire point: IG charges on what you control, not what you put up."""
    assert notional_of(position()) == Decimal("1729.44")


def test_notional_falls_back_to_the_opening_level():
    row = position(current_level=None, open_level=Decimal("50000"))
    assert notional_of(row) == Decimal("1500.00")


def test_no_price_means_no_invented_number():
    assert notional_of(position(current_level=None, open_level=None)) is None


def test_nightly_charge_uses_benchmark_plus_premium():
    charge, rate = nightly_charge(Decimal("31400"), 4.0, 3.0)
    assert rate == Decimal("7.0")
    # 31400 * 7% / 365
    assert charge == pytest.approx(Decimal("6.0219"), abs=Decimal("0.001"))


def test_the_projection_answers_the_question_roger_is_asking():
    """He holds leveraged positions for three to four months."""
    quarterly = project(Decimal("31400"), 4.0, 3.0, 105)
    assert quarterly == pytest.approx(Decimal("632.30"), abs=Decimal("1"))
    assert per_month(Decimal("31400"), 4.0, 3.0) == pytest.approx(
        Decimal("180.66"), abs=Decimal("0.5")
    )


def test_only_daily_funded_products_accrue():
    """Dated products and options carry financing in the price. Charging them
    again would invent a cost that is already paid."""
    assert is_daily_funded("DFB")
    assert is_daily_funded("-")
    assert is_daily_funded(None)
    assert not is_daily_funded("SEP-26")
    assert not is_daily_funded("2026-09-18")


def test_charge_scales_linearly_with_the_holding_period():
    one = project(Decimal("10000"), 4.0, 3.0, 30)
    four = project(Decimal("10000"), 4.0, 3.0, 120)
    assert four == pytest.approx(one * 4, abs=Decimal("0.05"))
