"""The rules that make a backtest a backtest rather than a story."""

from datetime import date, timedelta

import pytest

from app.backtest import Costs, apply_costs, bootstrap_returns, expected_report_date


def test_expected_date_uses_same_quarter_last_year():
    """A company that reported Q1 on 20 April is expected to report the next
    Q1 about a year later, on the same weekday cadence."""
    prior = [
        (date(2023, 3, 31), date(2023, 4, 20)),
        (date(2023, 6, 30), date(2023, 7, 20)),
    ]
    expected = expected_report_date(prior, date(2024, 3, 31))
    assert expected == date(2023, 4, 20) + timedelta(days=364)


def test_expected_date_falls_back_to_median_lag():
    """With no matching quarter a year back, the median reporting lag is used."""
    prior = [
        (date(2023, 3, 31), date(2023, 5, 10)),
        (date(2023, 6, 30), date(2023, 8, 9)),
    ]
    expected = expected_report_date(prior, date(2023, 9, 30))
    assert expected == date(2023, 9, 30) + timedelta(days=40)


def test_expected_date_is_none_without_history():
    """No basis for an expectation means no trade, not a guessed date."""
    assert expected_report_date([], date(2024, 3, 31)) is None


def test_same_quarter_branch_cannot_use_the_period_it_is_predicting():
    """Defence in depth on the lookahead rule.

    A period is never ~364 days from itself, so the same-quarter-last-year
    branch structurally cannot pick up the target period's own report date
    even if a caller passed it in.
    """
    period = date(2024, 3, 31)
    prior = [(date(2023, 3, 31), date(2023, 4, 20))]

    honest = expected_report_date(prior, period)
    contaminated = expected_report_date(prior + [(period, date(2024, 4, 25))], period)

    assert honest == date(2023, 4, 20) + timedelta(days=364)
    assert contaminated == honest


def test_median_lag_branch_is_contaminated_by_the_target_period():
    """Why run_pre_earnings must filter before calling.

    The fallback branch has no such structural protection: hand it the target
    period's own lag and the answer shifts. This is the leak the caller closes
    by passing only periods that had already reported, and it is asserted here
    so nobody "simplifies" that filter away.
    """
    period = date(2024, 6, 30)
    # Lags of 40 and 61 days, so the median is 50.
    prior = [
        (date(2023, 9, 30), date(2023, 11, 9)),
        (date(2023, 12, 31), date(2024, 3, 1)),
    ]

    honest = expected_report_date(prior, period)
    # A 5-day lag on the target period itself drags the median down to 40.
    contaminated = expected_report_date(prior + [(period, date(2024, 7, 5))], period)

    assert honest == period + timedelta(days=50)
    assert contaminated == period + timedelta(days=40)


def test_costs_are_charged_on_both_legs():
    """Spread and commission are each paid twice, entering and leaving."""
    net = apply_costs(1.0, holding_days=6, costs=Costs(spread_bps=10, commission_bps=5))
    assert net == pytest.approx(1.0 - 0.30)


def test_funding_only_applies_when_leveraged():
    unlevered = apply_costs(1.0, 10, Costs(spread_bps=0, commission_bps=0, funding_annual_pct=5.0))
    levered = apply_costs(
        1.0, 10, Costs(spread_bps=0, commission_bps=0, funding_annual_pct=5.0, leveraged=True)
    )
    assert unlevered == pytest.approx(1.0)
    assert levered == pytest.approx(1.0 - 5.0 * 10 / 365)


def test_bootstrap_flags_a_result_that_straddles_zero():
    """Returns centred on zero must be reported as indistinguishable from noise."""
    result = bootstrap_returns([1.0, -1.0] * 100, iterations=200)
    assert result is not None
    assert result.inside_noise is True


def test_bootstrap_needs_a_sample():
    assert bootstrap_returns([0.1] * 5) is None
