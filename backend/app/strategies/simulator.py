"""Portfolio simulation over the rule engine.

The same evaluate() the nightly paper run uses, replayed over history. Fills
happen at the NEXT trading day's open — a signal computed from today's close
cannot be filled at today's close, because that price had already printed
before the signal existed.

Dividends and corporate actions are handled through adjusted prices: fills and
marks both live in total-return space, which credits dividends by reinvestment.
A cash dividend line-item ledger would be more literal; this is the honest
approximation, and it is stated rather than hidden.
"""

import logging
import statistics
from dataclasses import dataclass, field
from datetime import date

from app.strategies.engine import Holding, evaluate
from app.strategies.features import FeatureService
from app.strategies.rules import StrategyRules

logger = logging.getLogger(__name__)

STARTING_CAPITAL = 100_000.0


@dataclass(frozen=True)
class CostModel:
    """Spread by liquidity tier, flat commission. Configurable, deliberately
    not optimistic."""

    commission_per_order: float = 2.0
    us_large_bps: float = 5.0    # >= $10bn
    us_mid_bps: float = 10.0     # $2bn - $10bn
    us_small_bps: float = 20.0   # < $2bn
    uk_bps: float = 40.0

    def spread_bps(self, quote_currency: str | None, market_cap: float | None) -> float:
        if quote_currency in ("GBX", "GBP"):
            return self.uk_bps
        if market_cap is None:
            return self.us_small_bps  # unknown size priced as illiquid, not free
        if market_cap >= 10e9:
            return self.us_large_bps
        if market_cap >= 2e9:
            return self.us_mid_bps
        return self.us_small_bps


@dataclass
class SimTrade:
    ticker: str
    side: str
    quantity: float
    price: float
    spread_cost: float
    commission: float
    signal_date: date
    fill_date: date
    rule_fired: str
    metric_values: dict


@dataclass
class RoundTrip:
    ticker: str
    entry_date: date
    exit_date: date
    entry_rule: str
    exit_rule: str
    net_return_pct: float
    holding_days: int


@dataclass
class SimResult:
    trades: list[SimTrade]
    round_trips: list[RoundTrip]
    equity_curve: list[tuple[date, float]]
    final_equity: float
    total_costs: float
    skipped_no_fill: int

    def monthly_returns(self) -> list[dict]:
        """Month-end equity to month-end equity, for the novelty gate."""
        by_month: dict[str, float] = {}
        for day, equity in self.equity_curve:
            by_month[f"{day.year:04d}-{day.month:02d}"] = equity
        months = sorted(by_month)
        out = []
        for previous, current in zip(months, months[1:]):
            if by_month[previous] > 0:
                out.append({
                    "month": current,
                    "return_pct": round((by_month[current] / by_month[previous] - 1) * 100, 4),
                })
        return out


def max_drawdown_pct(curve: list[tuple[date, float]]) -> float:
    peak = float("-inf")
    worst = 0.0
    for _, equity in curve:
        peak = max(peak, equity)
        if peak > 0:
            worst = min(worst, (equity / peak - 1) * 100)
    return round(worst, 2)


def _fill_orders(
    service: FeatureService,
    rules: StrategyRules,
    costs: CostModel,
    orders,
    holdings: dict[str, Holding],
    fill_day: date,
    target_count: int,
    state: dict,
    trades: list,
    round_trips: list,
) -> None:
    """Execute one day's orders at that day's open. Sells first: they free the
    cash the buys will spend."""
    ordered = sorted(orders, key=lambda o: o.side != "sell")

    for order in ordered:
        security = service.securities.get(order.ticker)
        fill = service.open_price(order.ticker, fill_day)
        market_cap = order.metric_values.get("price:market_cap")
        spread_bps = costs.spread_bps(security.quote_currency if security else None, market_cap)

        if order.side == "sell":
            holding = holdings.get(order.ticker)
            if holding is None:
                continue
            if fill is None:
                # No print on the fill day (halt, delisting gap): close at the
                # last known mark rather than carrying a ghost position forever.
                index = service._bar_index(order.ticker, fill_day)
                if index < 0:
                    state["skipped"] += 1
                    continue
                fill = service.bars[order.ticker][index].adjusted_close
            gross = holding.quantity * fill
            spread_cost = gross * spread_bps / 10_000
            proceeds = gross - spread_cost - costs.commission_per_order
            state["cash"] += proceeds
            state["costs"] += spread_cost + costs.commission_per_order
            trades.append(SimTrade(order.ticker, "sell", holding.quantity, fill,
                                   spread_cost, costs.commission_per_order,
                                   order.signal_date, fill_day,
                                   order.rule_fired, order.metric_values))
            basis = holding.quantity * holding.avg_cost
            if basis > 0:
                round_trips.append(RoundTrip(
                    ticker=order.ticker,
                    entry_date=holding.opened,
                    exit_date=fill_day,
                    entry_rule=holding.rule_fired,
                    exit_rule=order.rule_fired,
                    net_return_pct=round((proceeds / basis - 1) * 100, 4),
                    holding_days=(fill_day - holding.opened).days,
                ))
            del holdings[order.ticker]

    buys = [o for o in ordered if o.side == "buy"]
    if not buys:
        return

    # Equal weight across the whole target book, sized on post-sell equity.
    equity = state["cash"]
    for ticker, holding in holdings.items():
        index = service._bar_index(ticker, fill_day)
        if index >= 0:
            equity += holding.quantity * service.bars[ticker][index].adjusted_close
    per_position = equity / max(target_count, 1)

    for order in buys:
        fill = service.open_price(order.ticker, fill_day)
        if fill is None or fill <= 0:
            state["skipped"] += 1
            continue
        security = service.securities.get(order.ticker)
        market_cap = order.metric_values.get("price:market_cap")
        spread_bps = costs.spread_bps(security.quote_currency if security else None, market_cap)
        budget = min(per_position, state["cash"])
        if budget <= 0 or budget < fill:
            state["skipped"] += 1
            continue
        spread_cost = budget * spread_bps / 10_000
        investable = budget - spread_cost - costs.commission_per_order
        if investable <= 0:
            state["skipped"] += 1
            continue
        quantity = investable / fill
        state["cash"] -= budget
        state["costs"] += spread_cost + costs.commission_per_order
        trades.append(SimTrade(order.ticker, "buy", quantity, fill,
                               spread_cost, costs.commission_per_order,
                               order.signal_date, fill_day,
                               order.rule_fired, order.metric_values))
        holdings[order.ticker] = Holding(
            ticker=order.ticker, opened=fill_day, quantity=quantity,
            # Cost basis includes the friction paid to get in.
            avg_cost=budget / quantity,
            rule_fired=order.rule_fired, metric_values=order.metric_values,
        )


def simulate(
    service: FeatureService,
    rules: StrategyRules,
    start: date,
    end: date,
    costs: CostModel | None = None,
    capital: float = STARTING_CAPITAL,
) -> SimResult:
    costs = costs or CostModel()
    holdings: dict[str, Holding] = {}
    trades: list[SimTrade] = []
    round_trips: list[RoundTrip] = []
    curve: list[tuple[date, float]] = []
    state = {"cash": capital, "costs": 0.0, "skipped": 0}

    rebalance_days = {
        d for d in service.rebalance_dates(rules.rebalance.frequency) if start <= d <= end
    }
    trading_days = [d for d in service.calendar if start <= d <= end]

    def mark(day: date) -> float:
        value = state["cash"]
        for ticker, holding in holdings.items():
            index = service._bar_index(ticker, day)
            if index >= 0:
                value += holding.quantity * service.bars[ticker][index].adjusted_close
        return value

    # Walk every trading day. The book is marked daily, so the drawdown is the
    # real one rather than the one that happens to be visible at rebalance
    # points, and the monthly return series is genuinely monthly whatever the
    # rebalance frequency is. Rebalance work happens only on signal days, and
    # its orders fill on the FOLLOWING trading day.
    pending: tuple[date, list, int] | None = None
    for today in trading_days:
        if pending is not None and pending[0] == today:
            _fill_orders(service, rules, costs, pending[1], holdings, today,
                         pending[2], state, trades, round_trips)
            pending = None

        if today in rebalance_days:
            decision = evaluate(service, rules, today, holdings)
            fill_day = service.next_trading_day(today)
            if fill_day is not None and fill_day <= end and decision.orders:
                pending = (fill_day, decision.orders, len(decision.target))

        curve.append((today, round(mark(today), 2)))

    if not curve:
        curve.append((end, capital))

    return SimResult(
        trades=trades,
        round_trips=round_trips,
        equity_curve=curve,
        final_equity=curve[-1][1],
        total_costs=round(state["costs"], 2),
        skipped_no_fill=state["skipped"],
    )


def summarise(result: SimResult, capital: float = STARTING_CAPITAL) -> dict:
    returns = [t.net_return_pct for t in result.round_trips]
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]
    out = {
        "trades": len(result.trades),
        "round_trips": len(returns),
        "total_return_pct": round((result.final_equity / capital - 1) * 100, 2),
        "final_equity": result.final_equity,
        "total_costs": result.total_costs,
        "max_drawdown_pct": max_drawdown_pct(result.equity_curve),
        "skipped_no_fill": result.skipped_no_fill,
    }
    if returns:
        out["mean_trade_return_pct"] = round(statistics.fmean(returns), 4)
        out["median_trade_return_pct"] = round(statistics.median(returns), 4)
        out["win_rate"] = round(len(wins) / len(returns), 4)
        out["mean_holding_days"] = round(
            statistics.fmean([t.holding_days for t in result.round_trips]), 1
        )
        if len(returns) > 2:
            out["stdev_trade_return_pct"] = round(statistics.pstdev(returns), 4)
        if wins and losses:
            # Expectancy in R, with R defined as the average losing trade —
            # the empirical risk unit for a rules-based book with no stops.
            avg_loss = abs(statistics.fmean(losses))
            if avg_loss > 0:
                out["expectancy_r"] = round(statistics.fmean(returns) / avg_loss, 4)
    return out
