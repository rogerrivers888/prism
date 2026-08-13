"""Engine and simulator invariants on synthetic data, where every correct
answer is knowable by hand."""

import datetime
from datetime import date

from app.fundamentals import Security
from app.strategies.engine import Holding, evaluate
from app.strategies.features import Bar, FeatureService
from app.strategies.rules import parse_rules
from app.strategies.simulator import CostModel, simulate, summarise


def make_service(price_paths: dict[str, list[float]], start=date(2024, 1, 1)):
    """A tiny in-memory market: one bar per weekday, price path given."""
    bars = {}
    securities = {}
    calendar = []
    for ticker, path in price_paths.items():
        series = []
        day = start
        for price in path:
            while day.weekday() >= 5:
                day += datetime.timedelta(days=1)
            series.append(Bar(day, price, price, price))
            day += datetime.timedelta(days=1)
        bars[ticker] = series
        securities[ticker] = Security(
            ticker=ticker, name=ticker, sector="hardware",
            quote_currency="USD", currency="USD", is_active=True,
        )
    calendar = sorted({b.date for s in bars.values() for b in s})
    first = min(b.date for s in bars.values() for b in s)
    last = max(b.date for s in bars.values() for b in s)
    return FeatureService(
        start=first, end=last, securities=securities, bars=bars,
        fundamentals={}, lens_scores={}, lens_scores_abs={}, dispersion={},
        sector_cycle={}, calendar=calendar,
    )


def rules_top1_momentum(mode="reconstitute", frequency="monthly"):
    return parse_rules({
        "universe": {},
        "entry": {"kind": "compare", "id": "has_momentum",
                  "feature": "price:return_1m", "op": "gt", "value": -1000},
        "rank": {"components": [{"feature": "price:return_1m", "direction": "desc"}],
                 "top_n": 1},
        "rebalance": {"frequency": frequency, "mode": mode},
        "sizing": {"max_positions": 1},
        **({"exit": {"kind": "held_days", "id": "time_stop", "op": "gte", "value": 30}}
           if mode == "hold_until_exit" else {}),
    })


def test_missing_feature_fails_the_condition_not_passes_it():
    """A rule that cannot be checked has not been satisfied."""
    service = make_service({"AAA": [100.0] * 10})  # 10 bars: no return_1m yet
    rules = rules_top1_momentum()
    decision = evaluate(service, rules, service.calendar[-1], {})
    assert decision.passed_entry == 0
    assert decision.orders == []


def test_winner_is_selected_and_reasons_recorded():
    up = [100 * (1.01 ** i) for i in range(60)]
    down = [100 * (0.99 ** i) for i in range(60)]
    service = make_service({"UP": up, "DOWN": down})
    decision = evaluate(service, rules_top1_momentum(), service.calendar[-1], {})
    buys = [o for o in decision.orders if o.side == "buy"]
    assert [o.ticker for o in buys] == ["UP"]
    assert "rank_1_of_1" in buys[0].rule_fired
    # The evidence travels with the order.
    assert "price:return_1m" in buys[0].metric_values


def test_reconstitute_sells_what_dropped_out():
    up = [100 * (1.01 ** i) for i in range(60)]
    down = [100 * (0.99 ** i) for i in range(60)]
    service = make_service({"UP": up, "DOWN": down})
    holdings = {"DOWN": Holding("DOWN", service.calendar[0], 10, 100, "test", {})}
    decision = evaluate(service, rules_top1_momentum(), service.calendar[-1], holdings)
    sells = [o for o in decision.orders if o.side == "sell"]
    assert [o.ticker for o in sells] == ["DOWN"]
    assert "dropped_out_of_ranking" in sells[0].rule_fired


def test_hold_mode_exits_on_held_days_and_records_which_rule():
    service = make_service({"AAA": [100.0 + i * 0.1 for i in range(120)]})
    rules = rules_top1_momentum(mode="hold_until_exit")
    opened = service.calendar[0]
    holdings = {"AAA": Holding("AAA", opened, 10, 100, "entry", {})}
    late = service.calendar[-1]
    decision = evaluate(service, rules, late, holdings)
    sells = [o for o in decision.orders if o.side == "sell"]
    assert len(sells) == 1
    assert sells[0].rule_fired == "exit:time_stop"


def test_simulation_fills_next_day_open_never_signal_day():
    up = [100 * (1.01 ** i) for i in range(80)]
    service = make_service({"UP": up})
    rules = rules_top1_momentum()
    result = simulate(service, rules, service.calendar[30], service.calendar[-1],
                      costs=CostModel(commission_per_order=0))
    assert result.trades, "expected at least one fill"
    for trade in result.trades:
        assert trade.fill_date > trade.signal_date


def test_costs_reduce_equity_and_are_accounted():
    flat = [100.0] * 80
    service = make_service({"AAA": flat})
    rules = rules_top1_momentum()
    free = simulate(service, rules, service.calendar[30], service.calendar[-1],
                    costs=CostModel(commission_per_order=0, us_small_bps=0,
                                    us_mid_bps=0, us_large_bps=0))
    costly = simulate(service, rules, service.calendar[30], service.calendar[-1],
                      costs=CostModel(commission_per_order=5, us_small_bps=50,
                                      us_mid_bps=50, us_large_bps=50))
    # A flat market with costs must end below one without.
    assert costly.final_equity < free.final_equity
    assert costly.total_costs > 0


def test_uk_spread_tier_is_widest():
    model = CostModel()
    assert model.spread_bps("GBX", 1e9) > model.spread_bps("USD", 50e9)
    # Unknown size is priced as illiquid, not as free.
    assert model.spread_bps("USD", None) == model.us_small_bps


def test_summary_reports_round_trips_and_drawdown():
    boom_bust = [100 + i for i in range(40)] + [140 - i for i in range(40)]
    service = make_service({"AAA": boom_bust})
    rules = rules_top1_momentum()
    result = simulate(service, rules, service.calendar[25], service.calendar[-1])
    summary = summarise(result)
    assert summary["max_drawdown_pct"] <= 0
    assert summary["trades"] == len(result.trades)


def test_equity_is_marked_every_trading_day_not_just_on_rebalances():
    """Drawdown measured only at rebalance points misses the drawdown.

    A crash that happens and recovers between two quarterly marks would be
    invisible, and the monthly return series would actually be quarterly —
    which silently corrupts Sharpe and the track-record maths downstream.
    """
    path = [100.0] * 30 + [50.0] + [100.0] * 49  # one-day crash mid-window
    service = make_service({"AAA": path})
    rules = rules_top1_momentum(frequency="quarterly")
    result = simulate(service, rules, service.calendar[25], service.calendar[-1],
                      costs=CostModel(commission_per_order=0, us_small_bps=0,
                                      us_mid_bps=0, us_large_bps=0))
    marked = {d for d, _ in result.equity_curve}
    expected = {d for d in service.calendar if d >= service.calendar[25]}
    assert marked == expected


def test_monthly_returns_are_monthly_even_when_rebalancing_quarterly():
    path = [100 * (1.002 ** i) for i in range(200)]
    service = make_service({"AAA": path})
    result = simulate(service, rules_top1_momentum(frequency="quarterly"),
                      service.calendar[30], service.calendar[-1])
    months = [row["month"] for row in result.monthly_returns()]
    assert len(months) == len(set(months))
    # ~170 trading days is roughly eight months, not two quarters.
    assert len(months) >= 5


def test_membership_governs_eligibility_when_present():
    """The survivorship repair: a departed company is eligible while it was a
    member — even though is_active says it is dead today — and a current
    member is invisible before it joined."""
    up = [100 * (1.01 ** i) for i in range(60)]
    service = make_service({"DEAD": up, "NEWBIE": [p * 0.9 for p in up]})
    # DEAD is delisted today; NEWBIE joined the index after our test date.
    service.securities["DEAD"].is_active = False
    last = service.calendar[-1]
    service.membership = {
        "DEAD": [(service.calendar[0], None)],
        # NEWBIE joins the day after the evaluation date.
        "NEWBIE": [(last + datetime.timedelta(days=1), None)],
    }

    decision = evaluate(service, rules_top1_momentum(), last, {})
    buys = [o.ticker for o in decision.orders if o.side == "buy"]
    assert buys == ["DEAD"]


def test_without_membership_is_active_still_filters():
    up = [100 * (1.01 ** i) for i in range(60)]
    service = make_service({"DEAD": up})
    service.securities["DEAD"].is_active = False
    decision = evaluate(service, rules_top1_momentum(), service.calendar[-1], {})
    assert decision.orders == []
