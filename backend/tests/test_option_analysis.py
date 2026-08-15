"""The four numbers, and the cases where they must refuse or warn."""

from datetime import date

import pytest

from app.options.analysis import analyse

TODAY = date(2026, 8, 15)
EXPIRY = date(2026, 9, 18)


def contract(**overrides):
    base = dict(
        deal_id="D1", underlying="NVDA", right="call", strike=220.0, expiry=EXPIRY,
        contracts=1.0, multiplier=100.0, direction="long", currency="USD",
        mark=13.45, spot=205.0, as_of=TODAY,
    )
    base.update(overrides)
    return analyse(**base)


def test_breakeven_states_the_price_the_date_and_the_move_required():
    view = contract()
    assert "must reach" in view.breakeven_line
    assert "18 Sep" in view.breakeven_line
    assert "34 days" in view.breakeven_line
    assert view.breakeven_price == pytest.approx(233.45, abs=0.01)
    assert view.move_required_pct == pytest.approx(13.9, abs=0.2)


def test_time_decay_is_expressed_in_money_per_day_not_as_a_greek():
    view = contract()
    assert "per day" in view.decay_line
    assert "$" in view.decay_line
    assert "theta" not in view.decay_line.lower()
    assert view.theta_per_day_money < 0


def test_decay_is_income_for_a_written_option_and_says_so():
    view = contract(direction="short")
    assert "in your favour" in view.decay_line
    assert view.theta_per_day_money > 0


def test_leverage_shows_exposure_and_multiplies_both_ways():
    view = contract()
    assert "You control" in view.leverage_line
    assert "10% fall" in view.leverage_line
    assert "applies upwards" in view.leverage_line
    # Exposure must exceed what was paid, or there is no leverage to warn about.
    assert view.exposure > view.position_value


def test_long_options_state_the_premium_as_the_maximum_loss():
    view = contract()
    assert "Maximum loss" in view.max_loss_line
    assert "go to zero" in view.max_loss_line


def test_written_calls_say_losses_are_not_capped():
    """The single most dangerous position type to display casually."""
    view = contract(direction="short")
    assert "NOT capped" in view.max_loss_line
    assert "unlimited" in view.max_loss_line
    assert "uncapped_loss" in view.warnings


def test_written_puts_state_the_bounded_but_large_worst_case():
    view = contract(direction="short", right="put")
    assert "NOT capped" in view.max_loss_line
    assert "falls to zero" in view.max_loss_line


def test_probability_is_labelled_an_approximation_from_delta():
    view = contract()
    assert "%" in view.probability_line
    assert "approximation" in view.probability_line
    assert "market's own estimate" in view.probability_line
    # And the correction Roger needs: people guess higher.
    assert "higher" in view.probability_line
    assert 0 < view.probability < 1


def test_earnings_before_expiry_warns_about_the_crush():
    view = contract(next_earnings=date(2026, 8, 27))
    assert view.earnings_warning is not None
    assert "27 Aug" in view.earnings_warning
    assert "fall sharply" in view.earnings_warning
    assert "earnings_before_expiry" in view.warnings


def test_earnings_after_expiry_is_not_a_warning():
    view = contract(next_earnings=date(2026, 10, 30))
    assert view.earnings_warning is None
    assert "earnings_before_expiry" not in view.warnings


def test_missing_prices_refuse_rather_than_print_zero():
    """A confident zero is worse than an admission."""
    view = contract(mark=None, spot=None)
    assert "cannot be" in view.decay_line
    assert "cannot be" in view.leverage_line
    assert view.theta_per_day_money is None
    assert "0" != view.decay_line


def test_an_expired_contract_says_so_rather_than_modelling_it():
    view = contract(as_of=date(2026, 9, 19))
    assert "expired" in view.breakeven_line.lower()
    assert view.days_left < 0


def test_implied_volatility_is_always_flagged_estimated():
    """IG does not quote IV, so ours is solved from the mark. Presenting an
    inferred number as a quoted one would be a lie with a decimal point."""
    view = contract()
    assert view.iv_estimated is True
    assert view.implied_volatility is not None


def test_premium_paid_is_preferred_over_the_current_mark_for_breakeven():
    """Breakeven depends on what you actually paid, not what it is worth now."""
    cheap = contract(premium_paid=500.0)
    dear = contract(premium_paid=3000.0)
    assert dear.breakeven_price > cheap.breakeven_price
