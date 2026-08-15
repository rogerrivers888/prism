"""What an option contract actually costs you, in plain English.

Options kill retail accounts through costs nobody shows them: time decay
that never appears on a statement, leverage that multiplies losses as
enthusiastically as gains, and a probability of success far lower than it
feels. Prism's job on this screen is to put every one of those in front of
Roger in pounds and days, every single day.

Four lines per contract, always, plus the market's own odds and a warning
when earnings fall before expiry. Where a number cannot be computed honestly
the line says so — a confident zero is worse than an admission.
"""

import logging
from dataclasses import dataclass, field
from datetime import date

from app.options.maths import (
    black_scholes,
    breakeven,
    implied_vol,
    intrinsic,
    probability_itm,
    year_fraction,
)

logger = logging.getLogger(__name__)


def money(amount: float, currency: str = "GBP") -> str:
    symbol = {"GBP": "£", "USD": "$", "EUR": "€"}.get((currency or "GBP").upper(), "")
    return f"{symbol}{abs(amount):,.0f}" if abs(amount) >= 100 else f"{symbol}{abs(amount):,.2f}"


@dataclass
class ContractView:
    """Everything the Book screen shows for one option contract."""

    deal_id: str
    underlying: str | None
    right: str
    strike: float
    expiry: date
    contracts: float
    multiplier: float
    direction: str
    currency: str
    days_left: int

    # The four numbers.
    breakeven_line: str
    decay_line: str
    leverage_line: str
    max_loss_line: str
    # The market's own odds.
    probability_line: str
    # Volatility crush, when earnings land before expiry.
    earnings_warning: str | None = None

    # Raw figures behind the prose, for tables and sorting.
    breakeven_price: float | None = None
    move_required_pct: float | None = None
    theta_per_day_money: float | None = None
    exposure: float | None = None
    position_value: float | None = None
    delta: float | None = None
    implied_volatility: float | None = None
    iv_estimated: bool = True
    probability: float | None = None
    warnings: list[str] = field(default_factory=list)


def analyse(
    *,
    deal_id: str,
    underlying: str | None,
    right: str,
    strike: float,
    expiry: date,
    contracts: float,
    multiplier: float,
    direction: str,
    currency: str,
    mark: float | None,
    spot: float | None,
    as_of: date,
    risk_free: float = 0.04,
    premium_paid: float | None = None,
    next_earnings: date | None = None,
) -> ContractView:
    """Turn one contract into the lines the screen shows.

    mark and spot are in the underlying's own units — the caller is
    responsible for unscaling IG's cents before this is reached.
    """
    days_left = (expiry - as_of).days
    years = year_fraction(as_of, expiry)
    long = direction.lower() == "long"
    size = abs(contracts) * multiplier

    view = ContractView(
        deal_id=deal_id, underlying=underlying, right=right, strike=strike,
        expiry=expiry, contracts=contracts, multiplier=multiplier,
        direction=direction, currency=currency, days_left=days_left,
        breakeven_line="", decay_line="", leverage_line="", max_loss_line="",
        probability_line="",
    )

    if days_left <= 0:
        view.breakeven_line = f"This contract expired on {expiry:%d %b}."
        view.decay_line = "No time value left — there is nothing further to decay."
        view.leverage_line = "Expired."
        view.max_loss_line = "Settled."
        view.probability_line = "Expired."
        return view

    # ---- (a) breakeven and deadline -------------------------------------
    # Premium per share: what was actually paid where known, otherwise
    # today's mark, which is what it would cost to open now.
    per_share = None
    if premium_paid is not None and size > 0:
        per_share = abs(premium_paid) / size
    elif mark is not None:
        per_share = mark

    if per_share is not None:
        level = breakeven(strike, per_share, right)
        view.breakeven_price = level
        if spot:
            move = (level / spot - 1.0) * 100.0
            view.move_required_pct = move
            direction_word = "reach" if move > 0 else "fall to"
            view.breakeven_line = (
                f"{underlying or 'The underlying'} must {direction_word} "
                f"{money(level, currency)} by {expiry:%d %b} for this to break even. "
                f"That is {move:+.1f}% from here, in {days_left} days."
            )
        else:
            view.breakeven_line = (
                f"Breaks even at {money(level, currency)} on {expiry:%d %b} "
                f"({days_left} days). No live price for the underlying, so the "
                "move required cannot be shown."
            )
    else:
        view.breakeven_line = (
            "Breakeven cannot be worked out: neither the premium paid nor a "
            "current price is available for this contract."
        )

    # ---- the model, used by the remaining lines -------------------------
    vol = None
    greeks = None
    if mark is not None and spot:
        vol = implied_vol(mark, spot, strike, years, risk_free, right)
        if vol is not None:
            greeks = black_scholes(spot, strike, years, risk_free, vol, right)
    view.implied_volatility = vol
    view.iv_estimated = True  # solved from the mark, never quoted by IG
    if greeks:
        view.delta = greeks.delta

    position_value = (mark * size) if mark is not None else None
    view.position_value = position_value

    # ---- (b) time decay, in money ---------------------------------------
    if greeks and size:
        # Theta is negative for a long option: a cost. For a written option
        # the same decay is income, and saying so avoids implying otherwise.
        decay = greeks.theta_per_day * size
        view.theta_per_day_money = decay if long else -decay
        if long:
            view.decay_line = (
                f"This position loses about {money(abs(decay), currency)} per day "
                "just from time passing, and that accelerates as expiry approaches."
            )
        else:
            view.decay_line = (
                f"Time decay works in your favour here: about "
                f"{money(abs(decay), currency)} per day, accelerating towards expiry — "
                "which is the compensation for taking uncapped risk."
            )
    else:
        view.decay_line = (
            "Time decay cannot be calculated without a current price for both "
            "the contract and the underlying."
        )

    # ---- (c) leverage, honestly -----------------------------------------
    if greeks and spot and size:
        exposure = abs(greeks.delta) * spot * size
        view.exposure = exposure
        if position_value and position_value > 0:
            # A 10% move in the underlying, run through delta, against what
            # the position is currently worth.
            shifted = black_scholes(spot * 0.9, strike, years, risk_free, vol, right)
            if shifted:
                change = (shifted.price - mark) / mark * 100.0
                view.leverage_line = (
                    f"You control {money(exposure, currency)} of {underlying or 'underlying'} "
                    f"exposure for {money(position_value, currency)}. A 10% fall in "
                    f"{underlying or 'the underlying'} is roughly a {change:+.0f}% move "
                    "in this position — and the same multiplication applies upwards."
                )
            else:
                view.leverage_line = (
                    f"You control {money(exposure, currency)} of exposure for "
                    f"{money(position_value, currency)}."
                )
        else:
            view.leverage_line = f"Controls about {money(exposure, currency)} of exposure."
    else:
        view.leverage_line = "Leverage cannot be calculated without a current price."

    # ---- (d) what you can lose ------------------------------------------
    if long:
        risked = abs(premium_paid) if premium_paid is not None else position_value
        if risked:
            view.max_loss_line = (
                f"Maximum loss: the {money(risked, currency)} premium — this can and "
                "often does go to zero at expiry. Nothing beyond that is at risk."
            )
        else:
            view.max_loss_line = (
                "Maximum loss is the premium paid, which can go to zero at expiry."
            )
    else:
        # A written option. The honest worst case is unbounded for a call.
        worst = (
            "unlimited — there is no ceiling on how far the underlying can rise"
            if right.lower() == "call"
            else f"up to {money(strike * size, currency)} if it falls to zero"
        )
        view.max_loss_line = (
            f"Losses are NOT capped on this position: {worst}. "
            "The premium received is the most you can make; the loss is not "
            "bounded by it."
        )
        view.warnings.append("uncapped_loss")

    # ---- the probability line -------------------------------------------
    if greeks:
        probability = probability_itm(greeks.delta, right)
        view.probability = probability
        view.probability_line = (
            f"The market is pricing this as roughly a {probability:.0%} chance of "
            f"expiring worth anything. That is an approximation taken from the "
            "option's delta, and it is the market's own estimate rather than a "
            "forecast — people consistently guess higher than this number."
        )
    else:
        view.probability_line = (
            "The market's implied odds cannot be calculated without a current price."
        )

    # ---- volatility crush ------------------------------------------------
    if next_earnings and as_of < next_earnings <= expiry:
        days_to_earnings = (next_earnings - as_of).days
        view.earnings_warning = (
            f"{underlying or 'This company'} reports earnings on "
            f"{next_earnings:%d %b}, {days_to_earnings} days from now and before this "
            f"contract expires on {expiry:%d %b}. Option prices typically fall sharply "
            "straight after results even when the share price moves your way, because "
            "the uncertainty they were pricing in has gone. Being right about the "
            "direction is not enough to make money through an earnings date."
        )
        view.warnings.append("earnings_before_expiry")

    if view.implied_volatility and view.implied_volatility > 0.8:
        view.warnings.append("very_high_iv")

    return view
