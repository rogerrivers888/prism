"""Option maths, and the cases where it must refuse to answer."""

import math
from datetime import date

import pytest

from app.options.maths import (
    black_scholes,
    breakeven,
    implied_vol,
    intrinsic,
    normal_cdf,
    probability_itm,
    year_fraction,
)


def test_normal_cdf_matches_known_values():
    assert normal_cdf(0) == pytest.approx(0.5)
    assert normal_cdf(1.96) == pytest.approx(0.975, abs=1e-3)
    assert normal_cdf(-1.96) == pytest.approx(0.025, abs=1e-3)


def test_put_call_parity_holds():
    """The strongest available check that the pricing is right."""
    spot, strike, years, rate, vol = 100.0, 95.0, 0.5, 0.04, 0.3
    call = black_scholes(spot, strike, years, rate, vol, "call")
    put = black_scholes(spot, strike, years, rate, vol, "put")
    parity = call.price - put.price
    expected = spot - strike * math.exp(-rate * years)
    assert parity == pytest.approx(expected, abs=1e-9)


def test_deep_in_the_money_call_approaches_intrinsic():
    g = black_scholes(200.0, 100.0, 0.05, 0.04, 0.2, "call")
    assert g.delta == pytest.approx(1.0, abs=1e-3)
    assert g.price == pytest.approx(200.0 - 100.0 * math.exp(-0.04 * 0.05), abs=0.5)


def test_time_decay_is_negative_for_a_long_option():
    """Theta must be a cost. A positive number here would tell Roger that
    waiting makes him money, which is the exact opposite of the truth."""
    for right in ("call", "put"):
        g = black_scholes(100.0, 100.0, 0.25, 0.04, 0.3, right)
        assert g.theta_per_day < 0


def test_decay_accelerates_towards_expiry():
    """The claim the screen makes in words has to be true in the numbers."""
    far = black_scholes(100.0, 100.0, 0.5, 0.04, 0.3, "call")
    near = black_scholes(100.0, 100.0, 0.02, 0.04, 0.3, "call")
    assert abs(near.theta_per_day) > abs(far.theta_per_day)


def test_implied_vol_recovers_the_input():
    for vol in (0.15, 0.35, 0.8):
        price = black_scholes(150.0, 160.0, 0.1, 0.04, vol, "call").price
        assert implied_vol(price, 150.0, 160.0, 0.1, 0.04, "call") == pytest.approx(vol, abs=1e-4)


def test_implied_vol_refuses_a_mark_below_intrinsic():
    """Stale marks and wide spreads produce these. Returning a number would
    invent a volatility that cannot exist."""
    # Intrinsic is 20; a mark of 5 is impossible.
    assert implied_vol(5.0, 120.0, 100.0, 0.25, 0.04, "call") is None


def test_implied_vol_refuses_rather_than_reporting_the_ceiling():
    absurd = black_scholes(100.0, 100.0, 0.25, 0.04, 4.9, "call").price * 1.5
    assert implied_vol(absurd, 100.0, 100.0, 0.25, 0.04, "call") is None


def test_expired_and_nonsense_inputs_return_none_not_zero():
    """A caller must be able to say 'cannot calculate' rather than print 0."""
    assert black_scholes(100.0, 100.0, 0.0, 0.04, 0.3, "call") is None
    assert black_scholes(100.0, 100.0, -0.5, 0.04, 0.3, "call") is None
    assert black_scholes(0.0, 100.0, 0.25, 0.04, 0.3, "call") is None
    assert black_scholes(100.0, 100.0, 0.25, 0.04, 0.0, "call") is None
    assert implied_vol(5.0, 100.0, 100.0, 0.0, 0.04, "call") is None


def test_breakeven_moves_the_right_way_for_each_right():
    # A call needs the underlying above strike plus what you paid.
    assert breakeven(160.0, 8.4, "call") == pytest.approx(168.4)
    # A put needs it below strike minus what you paid.
    assert breakeven(160.0, 8.4, "put") == pytest.approx(151.6)


def test_probability_is_the_absolute_delta_for_both_rights():
    call = black_scholes(100.0, 120.0, 0.25, 0.04, 0.3, "call")
    put = black_scholes(100.0, 80.0, 0.25, 0.04, 0.3, "put")
    assert 0 < probability_itm(call.delta, "call") < 0.5
    assert 0 < probability_itm(put.delta, "put") < 0.5


def test_year_fraction_and_intrinsic():
    assert year_fraction(date(2026, 8, 15), date(2026, 9, 19)) == pytest.approx(35 / 365)
    assert intrinsic(168.0, 160.0, "call") == 8.0
    assert intrinsic(168.0, 160.0, "put") == 0.0
