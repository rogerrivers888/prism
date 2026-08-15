"""Black-Scholes, implied volatility and the Greeks Prism actually uses.

Deliberately small. Prism computes four things — a fair value, an implied
volatility solved back out of a mark, a delta, and a theta — because those are
what the four plain-English lines on a contract need. Nothing here is an
options analytics engine and it should not grow into one without a reason.

Standard library only: erf gives the normal CDF, and implied volatility is
solved by bisection, which is slower than Newton and cannot diverge. On a
handful of contracts refreshed daily, robustness is worth more than speed.

Every number this module produces about a live position is an ESTIMATE unless
IG supplied it. Callers must carry that flag through to the screen: an
inferred volatility presented as a quoted one is a lie with a decimal point.
"""

import math
from dataclasses import dataclass
from datetime import date

# Below this many years to expiry the model stops being meaningful — on the
# last day an option is intrinsic value and a coin toss, not a diffusion.
MIN_YEARS = 1 / 365 / 4

# Bounds for the volatility search. 500% covers anything a listed equity
# option should ever imply; hitting the bound is a signal, not an answer.
MIN_VOL = 0.005
MAX_VOL = 5.0


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def normal_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def year_fraction(as_of: date, expiry: date) -> float:
    """Calendar years to expiry. Negative or zero means expired."""
    return (expiry - as_of).days / 365.0


@dataclass(frozen=True)
class Greeks:
    price: float
    delta: float
    # Per CALENDAR DAY, in the option's own price units. The screen turns this
    # into pounds; leaving it as a Greek is how the cost stays invisible.
    theta_per_day: float
    vega_per_point: float


def _d1_d2(spot, strike, years, rate, vol):
    variance = vol * math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate + 0.5 * vol * vol) * years) / variance
    return d1, d1 - variance


def black_scholes(
    spot: float,
    strike: float,
    years: float,
    rate: float,
    vol: float,
    right: str,
) -> Greeks | None:
    """European option value and the Greeks Prism uses.

    Returns None rather than a number when the inputs cannot support one —
    an expired contract, a zero price, a nonsensical volatility. A caller that
    gets None must say "cannot calculate", not print a zero.
    """
    if spot <= 0 or strike <= 0 or vol <= 0 or years <= MIN_YEARS:
        return None
    call = right.lower() == "call"

    d1, d2 = _d1_d2(spot, strike, years, rate, vol)
    discount = math.exp(-rate * years)

    if call:
        price = spot * normal_cdf(d1) - strike * discount * normal_cdf(d2)
        delta = normal_cdf(d1)
        theta_annual = (
            -(spot * normal_pdf(d1) * vol) / (2 * math.sqrt(years))
            - rate * strike * discount * normal_cdf(d2)
        )
    else:
        price = strike * discount * normal_cdf(-d2) - spot * normal_cdf(-d1)
        delta = normal_cdf(d1) - 1.0
        theta_annual = (
            -(spot * normal_pdf(d1) * vol) / (2 * math.sqrt(years))
            + rate * strike * discount * normal_cdf(-d2)
        )

    return Greeks(
        price=price,
        delta=delta,
        theta_per_day=theta_annual / 365.0,
        vega_per_point=spot * normal_pdf(d1) * math.sqrt(years) / 100.0,
    )


def intrinsic(spot: float, strike: float, right: str) -> float:
    return max(0.0, spot - strike) if right.lower() == "call" else max(0.0, strike - spot)


def implied_vol(
    mark: float,
    spot: float,
    strike: float,
    years: float,
    rate: float,
    right: str,
) -> float | None:
    """Solve volatility from an observed price, by bisection.

    Returns None when the mark cannot be produced by any volatility — most
    often because it sits below intrinsic value, which happens with stale
    marks and wide spreads and is worth surfacing rather than smoothing over.
    """
    if mark <= 0 or spot <= 0 or strike <= 0 or years <= MIN_YEARS:
        return None
    # A price below intrinsic is unattainable: no volatility produces it.
    if mark < intrinsic(spot, strike, right) - 1e-9:
        return None

    low, high = MIN_VOL, MAX_VOL
    price_at = lambda v: (black_scholes(spot, strike, years, rate, v, right) or Greeks(0, 0, 0, 0)).price

    if price_at(high) < mark:
        # Beyond the search ceiling: refuse rather than report 500%.
        return None

    for _ in range(100):
        mid = 0.5 * (low + high)
        if price_at(mid) < mark:
            low = mid
        else:
            high = mid
        if high - low < 1e-6:
            break
    vol = 0.5 * (low + high)
    return vol if MIN_VOL < vol < MAX_VOL else None


def probability_itm(delta: float, right: str) -> float:
    """The market's rough odds of expiring in the money.

    Delta is a serviceable approximation of that probability and it is the one
    number the market itself is quoting. It is an approximation — it ignores
    the drift term and treats the risk-neutral measure as a forecast — and
    every surface that shows it says so.
    """
    return abs(delta)


def breakeven(strike: float, premium_per_share: float, right: str) -> float:
    """Where the underlying must be at expiry for the trade to break even."""
    return (
        strike + premium_per_share
        if right.lower() == "call"
        else strike - premium_per_share
    )
