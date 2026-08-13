"""The first generation: twelve strategies, encoded from their sources.

Each entry states its authority and, where the encoding had to depart from the
published rule, says so in ``encoding_deviations``. Those deviations are the
most important text on the card: a strategy that claims to be Piotroski but
silently drops three of his nine tests is not Piotroski, and the difference
will show up as unexplained divergence from the literature later.

Predicted performance is written here, before any backtest runs. When the gate
disagrees, the prediction stays on the record.
"""

from app.strategies.registry import DEFAULT_DECAY_NOTE

# Roughly the S&P 500 floor; below this the universe is names Prism does not
# cover consistently.
MID_CAP = 2e9
LARGE_CAP = 10e9


def _own_idea_decay(note: str) -> str:
    return (
        note
        + " This one has no published track record at all, which means it has "
        "never survived anyone else's scrutiny — treat it as weaker evidence "
        "than a published anomaly, not stronger."
    )


CATALOGUE: list[dict] = [
    # ------------------------------------------------------------------ 1
    {
        "name": "Piotroski F-Score value",
        "authority": "Piotroski 2000",
        "citation": (
            "Piotroski, J. (2000). Value Investing: The Use of Historical Financial "
            "Statement Information to Separate Winners from Losers. Journal of "
            "Accounting Research 38, 1-41."
        ),
        "hypothesis": (
            "Cheap companies are cheap for a reason, and most of them deserve it. "
            "Piotroski's insight was that within the cheapest slice of the market, "
            "simple accounting health signals — profitable, cash-generative, less "
            "indebted than last year, improving margins — separate the businesses "
            "that are merely unloved from the ones that are actually dying. The "
            "screen should work because the cheapest decile is where analyst "
            "coverage is thinnest and mispricing survives longest."
        ),
        "horizon": "long",
        "expected_trade_frequency": "roughly 10-20 trades a year",
        "expected_holding_period": "a year or more",
        "predicted_performance": (
            "Positive expectancy over the full period, most of it earned in the "
            "recovery years after a drawdown. Expect long stretches of "
            "underperformance in growth-led markets, and a lower Sharpe than the "
            "paper reports because the paper's universe included microcaps we "
            "cannot trade."
        ),
        "encoding_deviations": (
            "F-score uses 8 of Piotroski's 9 components: the current-ratio test is "
            "dropped because Prism does not store current assets or current "
            "liabilities. Operating cash flow is proxied by free cash flow, which "
            "is stricter than the original (capex is subtracted). Piotroski ranked "
            "on book-to-market within the cheapest book-to-market quintile; this "
            "uses price-to-book in the cheapest 30%, which is the same measure "
            "inverted. His universe was all listed US firms including microcaps; "
            "ours is a large-cap index, where the effect has historically been "
            "much weaker."
        ),
        "rules": {
            "universe": {"min_market_cap": MID_CAP},
            "entry": {
                "kind": "all",
                "conditions": [
                    {"kind": "percentile", "id": "cheapest_30pc_on_book",
                     "feature": "metric:price_to_book", "op": "lte", "value": 30},
                    {"kind": "compare", "id": "f_score_at_least_7",
                     "feature": "special:piotroski_f", "op": "gte", "value": 7},
                ],
            },
            "rank": {"components": [{"feature": "special:piotroski_f", "direction": "desc"}],
                     "top_n": 20},
            "rebalance": {"frequency": "quarterly", "mode": "reconstitute"},
            "sizing": {"max_positions": 20},
        },
    },
    # ------------------------------------------------------------------ 2
    {
        "name": "Greenblatt Magic Formula",
        "authority": "Greenblatt 2005",
        "citation": (
            "Greenblatt, J. (2005). The Little Book That Beats the Market. Wiley."
        ),
        "hypothesis": (
            "Buy good businesses at cheap prices, using exactly two numbers: how "
            "much the business earns on the capital it employs, and how much those "
            "earnings cost you. Ranking on both and adding the ranks finds "
            "companies that are decent on each rather than exceptional on one — "
            "which is the point, because a top rank on cheapness alone is usually "
            "a company in trouble."
        ),
        "horizon": "long",
        "expected_trade_frequency": "about 30 trades a year",
        "expected_holding_period": "a year",
        "predicted_performance": (
            "Modest positive expectancy, well below the book's reported figures. "
            "The book's universe went down to $50m market caps where the effect "
            "was strongest; in large caps it has been close to flat since "
            "publication."
        ),
        "encoding_deviations": (
            "Return on capital uses invested capital as reported rather than "
            "Greenblatt's (net working capital + net fixed assets), which Prism "
            "does not store. Earnings yield is EBIT/enterprise value as in the "
            "book. Greenblatt excluded financials and utilities; that exclusion is "
            "encoded. He also excluded foreign companies, which is not encoded — "
            "the universe is filtered to US-quoted names instead."
        ),
        "rules": {
            "universe": {
                "min_market_cap": MID_CAP,
                "exclude_sectors": ["banks", "insurance", "financials", "utilities", "real_estate"],
                "quote_currencies": ["USD"],
            },
            "entry": {
                "kind": "all",
                "conditions": [
                    {"kind": "compare", "id": "positive_earnings_yield",
                     "feature": "special:earnings_yield_ebit", "op": "gt", "value": 0},
                    {"kind": "compare", "id": "positive_return_on_capital",
                     "feature": "special:roc_greenblatt", "op": "gt", "value": 0},
                ],
            },
            "rank": {
                "kind": "rank_sum",
                "components": [
                    {"feature": "special:earnings_yield_ebit", "direction": "desc"},
                    {"feature": "special:roc_greenblatt", "direction": "desc"},
                ],
                "top_n": 30,
            },
            "rebalance": {"frequency": "quarterly", "mode": "reconstitute"},
            "sizing": {"max_positions": 30},
        },
    },
    # ------------------------------------------------------------------ 3
    {
        "name": "Novy-Marx quality and value",
        "authority": "Novy-Marx 2013",
        "citation": (
            "Novy-Marx, R. (2013). The Other Side of Value: The Gross "
            "Profitability Premium. Journal of Financial Economics 108, 1-28."
        ),
        "hypothesis": (
            "Gross profits over total assets predicts returns about as well as "
            "book-to-market does, and the two are negatively correlated — "
            "profitable firms tend to be expensive, cheap firms tend to be "
            "unprofitable. Holding both together produces a portfolio that is "
            "better than either alone, because each leg hedges the other's "
            "characteristic failure."
        ),
        "horizon": "long",
        "expected_trade_frequency": "about 20 trades a year",
        "expected_holding_period": "a year",
        "predicted_performance": (
            "Positive but modest expectancy, with a smoother ride than pure value. "
            "Gross profitability is the least decayed of the classic anomalies, so "
            "less shrinkage than Piotroski or the Magic Formula — but still "
            "expect roughly half the paper's figure."
        ),
        "encoding_deviations": (
            "Gross profitability is gross profit over total assets, as in the "
            "paper. Novy-Marx sorted into deciles and went long-short; this is "
            "long-only, so it captures only the long leg and will look weaker than "
            "the published spread. Cheapness uses price-to-book, the inverse of "
            "his book-to-market."
        ),
        "rules": {
            "universe": {"min_market_cap": MID_CAP},
            "entry": {
                "kind": "all",
                "conditions": [
                    {"kind": "percentile", "id": "top_third_profitability",
                     "feature": "metric:gross_profitability", "op": "gte", "value": 67},
                    {"kind": "percentile", "id": "cheaper_half_on_book",
                     "feature": "metric:price_to_book", "op": "lte", "value": 50},
                ],
            },
            "rank": {
                "kind": "rank_sum",
                "components": [
                    {"feature": "metric:gross_profitability", "direction": "desc"},
                    {"feature": "metric:price_to_book", "direction": "asc"},
                ],
                "top_n": 25,
            },
            "rebalance": {"frequency": "quarterly", "mode": "reconstitute"},
            "sizing": {"max_positions": 25},
        },
    },
    # ------------------------------------------------------------------ 4
    {
        "name": "Jegadeesh-Titman 12-1 momentum",
        "authority": "Jegadeesh & Titman 1993",
        "citation": (
            "Jegadeesh, N. & Titman, S. (1993). Returns to Buying Winners and "
            "Selling Losers: Implications for Stock Market Efficiency. Journal of "
            "Finance 48, 65-91."
        ),
        "hypothesis": (
            "Stocks that went up over the past year keep going up for a few more "
            "months. The most recent month is skipped because it reverses — "
            "short-term buyers overshoot and the bounce back would eat the signal. "
            "The usual explanation is that investors underreact to news and the "
            "adjustment takes months rather than days."
        ),
        "horizon": "medium",
        "expected_trade_frequency": "very high — 100+ trades a year",
        "expected_holding_period": "1-3 months",
        "predicted_performance": (
            "Positive gross expectancy that costs will substantially erode given "
            "monthly turnover. Occasional violent drawdowns at market turns — "
            "momentum crashes are the defining risk and they arrive without "
            "warning. Expect a much worse maximum drawdown than the value screens."
        ),
        "encoding_deviations": (
            "Faithful to the 12-1 formation window and monthly rebalance. "
            "Jegadeesh & Titman held for 3-12 months in overlapping portfolios and "
            "went long-short by decile; this is long-only with a single monthly "
            "reconstitution, so it captures the long leg only and turns over "
            "faster than the paper."
        ),
        "rules": {
            "universe": {"min_market_cap": MID_CAP},
            "entry": {
                "kind": "percentile",
                "id": "top_decile_12_1",
                "feature": "price:return_12_1",
                "op": "gte",
                "value": 90,
            },
            "rank": {"components": [{"feature": "price:return_12_1", "direction": "desc"}],
                     "top_n": 20},
            "rebalance": {"frequency": "monthly", "mode": "reconstitute"},
            "sizing": {"max_positions": 20},
        },
    },
    # ------------------------------------------------------------------ 5
    {
        "name": "CANSLIM approximation",
        "authority": "O'Neil 1988 (approximation)",
        "citation": (
            "O'Neil, W. (1988). How to Make Money in Stocks. McGraw-Hill."
        ),
        "hypothesis": (
            "Buy companies with accelerating earnings whose shares are already "
            "among the strongest in the market and trading near highs. The claim "
            "is that institutional accumulation shows up in price strength before "
            "it shows up in the accounts everyone can see."
        ),
        "horizon": "medium",
        "expected_trade_frequency": "high — 60+ trades a year",
        "expected_holding_period": "months",
        "predicted_performance": (
            "Strong in trending bull markets, badly negative in corrections, with "
            "a high maximum drawdown. This is the entrant most likely to look "
            "spectacular over 2013-2021 and terrible over 2022 — which is exactly "
            "why the per-regime breakdown matters more here than the headline."
        ),
        "encoding_deviations": (
            "A genuine approximation, not an encoding. CANSLIM's letters cover "
            "current quarterly earnings, annual earnings, new products or "
            "management, supply and demand from share count, leader-vs-laggard, "
            "institutional sponsorship, and market direction. Prism can only reach "
            "the earnings acceleration (via the growth lens), relative strength, "
            "and price-near-high components. New products, management changes and "
            "institutional sponsorship are not in the data at all, and the market-"
            "direction filter is absent. Treat this as 'growth plus relative "
            "strength', not as CANSLIM."
        ),
        "rules": {
            "universe": {"min_market_cap": MID_CAP},
            "entry": {
                "kind": "all",
                "conditions": [
                    {"kind": "compare", "id": "strong_growth",
                     "feature": "lens:growth", "op": "gte", "value": 75},
                    {"kind": "compare", "id": "relative_strength_top_20pc",
                     "feature": "price:rs_rank", "op": "gte", "value": 80},
                    {"kind": "compare", "id": "within_15pc_of_52w_high",
                     "feature": "price:pct_off_52w_high", "op": "gte", "value": -15},
                    {"kind": "compare", "id": "above_200dma",
                     "feature": "price:price_vs_ma200", "op": "gt", "value": 0},
                ],
            },
            "rank": {"components": [{"feature": "price:rs_rank", "direction": "desc"}],
                     "top_n": 15},
            "rebalance": {"frequency": "monthly", "mode": "reconstitute"},
            "sizing": {"max_positions": 15},
        },
    },
    # ------------------------------------------------------------------ 6
    {
        "name": "Minervini trend template",
        "authority": "Minervini 2013",
        "citation": (
            "Minervini, M. (2013). Trade Like a Stock Market Wizard. McGraw-Hill. "
            "The eight-point trend template."
        ),
        "hypothesis": (
            "A stock in a genuine advance satisfies a specific stack of price "
            "conditions at once: above its long averages, the averages in the "
            "right order and rising, well off its low and near its high. The claim "
            "is not that these predict anything individually — it is that "
            "demanding all of them together filters out almost everything that is "
            "not already working."
        ),
        "horizon": "medium",
        "expected_trade_frequency": "moderate — 40-60 trades a year",
        "expected_holding_period": "months",
        "predicted_performance": (
            "Similar shape to CANSLIM: good in trends, poor at turns. Fewer "
            "positions pass the full stack than people expect, so expect stretches "
            "with almost nothing held, and a lumpy equity curve as a result."
        ),
        "encoding_deviations": (
            "Seven of Minervini's eight criteria are encoded. The missing one is "
            "'the 150-day average is above the 200-day average' — encoded — while "
            "his requirement that the 200-day has been trending up for at least a "
            "month is implemented as a three-month slope, which is stricter. His "
            "criteria are applied to price alone; no relative-strength-rank "
            "minimum is included here, since that is CANSLIM's job in this "
            "generation and duplicating it would blur the two."
        ),
        "rules": {
            "universe": {"min_market_cap": MID_CAP},
            "entry": {
                "kind": "all",
                "conditions": [
                    {"kind": "compare", "id": "above_150dma",
                     "feature": "price:price_vs_ma150", "op": "gt", "value": 0},
                    {"kind": "compare", "id": "above_200dma",
                     "feature": "price:price_vs_ma200", "op": "gt", "value": 0},
                    {"kind": "compare", "id": "ma50_above_ma200",
                     "feature": "price:ma50_vs_ma200", "op": "gt", "value": 0},
                    {"kind": "compare", "id": "above_50dma",
                     "feature": "price:price_vs_ma50", "op": "gt", "value": 0},
                    {"kind": "compare", "id": "ma200_rising_3m",
                     "feature": "price:ma200_slope_3m", "op": "gt", "value": 0},
                    {"kind": "compare", "id": "at_least_30pc_above_52w_low",
                     "feature": "price:pct_above_52w_low", "op": "gte", "value": 30},
                    {"kind": "compare", "id": "within_25pc_of_52w_high",
                     "feature": "price:pct_off_52w_high", "op": "gte", "value": -25},
                ],
            },
            "rank": {"components": [{"feature": "price:return_6m", "direction": "desc"}],
                     "top_n": 15},
            "rebalance": {"frequency": "monthly", "mode": "reconstitute"},
            "sizing": {"max_positions": 15},
        },
    },
    # ------------------------------------------------------------------ 7
    {
        "name": "Dual momentum",
        "authority": "Antonacci 2014",
        "citation": (
            "Antonacci, G. (2014). Dual Momentum Investing. McGraw-Hill."
        ),
        "hypothesis": (
            "Combine two filters: relative momentum picks what is strongest, and "
            "absolute momentum refuses to hold anything whose own twelve-month "
            "return is negative. The second filter is the one that matters — it is "
            "meant to step aside in bear markets rather than owning the "
            "best-performing thing in a falling market."
        ),
        "horizon": "medium",
        "expected_trade_frequency": "moderate — 40-60 trades a year",
        "expected_holding_period": "months",
        "predicted_performance": (
            "Lower return than pure momentum but a materially smaller maximum "
            "drawdown, because the absolute filter empties the book in sustained "
            "declines. If the drawdown is not smaller than plain 12-1 momentum, "
            "the absolute filter is not doing its job and the strategy has no "
            "reason to exist."
        ),
        "encoding_deviations": (
            "Antonacci applied dual momentum to asset classes — US equities, "
            "international equities, bonds — switching between them, with "
            "Treasury bills as the safe asset. Prism holds only single stocks, so "
            "this is dual momentum applied WITHIN a stock universe: relative "
            "momentum ranks, absolute momentum gates. There is no bond or cash leg "
            "to rotate into; when nothing passes, the strategy simply holds less. "
            "That is a real departure and it removes much of the original's "
            "defensive benefit."
        ),
        "rules": {
            "universe": {"min_market_cap": MID_CAP},
            "entry": {
                "kind": "all",
                "conditions": [
                    {"kind": "compare", "id": "absolute_momentum_positive",
                     "feature": "price:return_12m", "op": "gt", "value": 0},
                    {"kind": "percentile", "id": "relative_momentum_top_quintile",
                     "feature": "price:return_12m", "op": "gte", "value": 80},
                ],
            },
            "rank": {"components": [{"feature": "price:return_12m", "direction": "desc"}],
                     "top_n": 20},
            "rebalance": {"frequency": "monthly", "mode": "reconstitute"},
            "sizing": {"max_positions": 20},
        },
    },
    # ------------------------------------------------------------------ 8
    {
        "name": "52-week-high proximity",
        "authority": "George & Hwang 2004",
        "citation": (
            "George, T. & Hwang, C. (2004). The 52-Week High and Momentum "
            "Investing. Journal of Finance 59, 2145-2176."
        ),
        "hypothesis": (
            "How close a stock is to its own 52-week high predicts returns better "
            "than its past return does. The explanation is behavioural: the high "
            "is a salient anchor, traders hesitate to bid above it even on good "
            "news, and the delayed adjustment shows up as drift once the level "
            "gives way."
        ),
        "horizon": "medium",
        "expected_trade_frequency": "high — 80+ trades a year",
        "expected_holding_period": "1-3 months",
        "predicted_performance": (
            "Similar to 12-1 momentum but with somewhat different holdings; the "
            "paper argued it dominates. If its return stream correlates above 0.8 "
            "with the Jegadeesh-Titman entrant, the novelty gate should say so and "
            "one of the two should be retired rather than both kept."
        ),
        "encoding_deviations": (
            "Faithful to the ranking measure (price as a proportion of the "
            "52-week high). The paper used a long-short decile design with monthly "
            "rebalancing; this is long-only. No volume or liquidity screen beyond "
            "the market-cap floor."
        ),
        "rules": {
            "universe": {"min_market_cap": MID_CAP},
            "entry": {
                "kind": "percentile",
                "id": "nearest_decile_to_52w_high",
                "feature": "price:pct_off_52w_high",
                "op": "gte",
                "value": 90,
            },
            "rank": {"components": [{"feature": "price:pct_off_52w_high", "direction": "desc"}],
                     "top_n": 20},
            "rebalance": {"frequency": "monthly", "mode": "reconstitute"},
            "sizing": {"max_positions": 20},
        },
    },
    # ------------------------------------------------------------------ 9
    {
        "name": "Quality at a reasonable price",
        "authority": "Prism house strategy, 2026-08-13",
        "citation": None,
        "hypothesis": (
            "The cleanest expression of what Prism's lenses are for: demand a "
            "genuinely good business and refuse to pay a silly price for it. Not a "
            "published anomaly — a deliberately plain baseline that the more "
            "elaborate entrants should have to beat before they earn their "
            "complexity."
        ),
        "horizon": "long",
        "expected_trade_frequency": "low — 15-25 trades a year",
        "expected_holding_period": "a year or more",
        "predicted_performance": (
            "Mildly positive expectancy and a shallow drawdown. Its real job is as "
            "a control: if the cited academic strategies cannot beat this, their "
            "citations are doing the persuading rather than their edges."
        ),
        "encoding_deviations": (
            "No source to deviate from. Thresholds (quality above 70, value above "
            "50) were chosen as round numbers before any backtest, deliberately "
            "not tuned. If they are ever adjusted, that is a NEW strategy with "
            "this one as parent."
        ),
        "rules": {
            "universe": {"min_market_cap": MID_CAP},
            "entry": {
                "kind": "all",
                "conditions": [
                    {"kind": "compare", "id": "quality_above_70",
                     "feature": "lens:quality", "op": "gt", "value": 70},
                    {"kind": "compare", "id": "value_above_50",
                     "feature": "lens:value", "op": "gt", "value": 50},
                ],
            },
            "rank": {
                "kind": "rank_sum",
                "components": [
                    {"feature": "lens:quality", "direction": "desc"},
                    {"feature": "lens:value", "direction": "desc"},
                ],
                "top_n": 20,
            },
            "rebalance": {"frequency": "quarterly", "mode": "reconstitute"},
            "sizing": {"max_positions": 20},
        },
    },
    # ------------------------------------------------------------------ 10
    {
        "name": "Contrarian value with a quality floor",
        "authority": "Prism house strategy, 2026-08-13",
        "citation": (
            "In the spirit of De Bondt & Thaler (1985), Does the Stock Market "
            "Overreact?, Journal of Finance 40, 793-805 — but not an encoding of it."
        ),
        "hypothesis": (
            "Buy what is cheap and out of favour, but refuse the ones that are "
            "cheap because they are broken. The quality floor is the whole idea: "
            "pure contrarian screens are dominated by value traps, and a modest "
            "quality requirement should remove the worst of them without removing "
            "the discount that makes the trade."
        ),
        "horizon": "long",
        "expected_trade_frequency": "low — 15-25 trades a year",
        "expected_holding_period": "a year or more",
        "predicted_performance": (
            "The widest outcome range of the twelve. Either the quality floor does "
            "its job and this beats plain value, or it does not and this is a "
            "slower value trap. Expect a deep drawdown before any recovery, and a "
            "poor showing in any period ending in a growth-led market."
        ),
        "encoding_deviations": (
            "Not an encoding of De Bondt & Thaler, who sorted on three-to-five "
            "year past returns rather than on valuation. This uses Prism's own "
            "lenses: cheap on value, not falling apart on quality, unloved on "
            "momentum. The momentum ceiling is what makes it contrarian rather "
            "than merely a value screen."
        ),
        "rules": {
            "universe": {"min_market_cap": MID_CAP},
            "entry": {
                "kind": "all",
                "conditions": [
                    {"kind": "compare", "id": "very_cheap",
                     "feature": "lens:value", "op": "gt", "value": 80},
                    {"kind": "compare", "id": "quality_floor",
                     "feature": "lens:quality", "op": "gt", "value": 40},
                    {"kind": "compare", "id": "out_of_favour",
                     "feature": "lens:momentum", "op": "lt", "value": 30},
                ],
            },
            "rank": {"components": [{"feature": "lens:value", "direction": "desc"}],
                     "top_n": 20},
            "rebalance": {"frequency": "quarterly", "mode": "reconstitute"},
            "sizing": {"max_positions": 20},
        },
    },
    # ------------------------------------------------------------------ 11
    {
        "name": "Sector cycle rotation",
        "authority": "Prism house strategy, 2026-08-13 — no published authority",
        "citation": None,
        "hypothesis": (
            "Prism's cycle lens reads inventory, capacity and pricing for "
            "industries that have a boom-and-bust rhythm. If the lens has any "
            "information, the sectors whose median cycle reading is IMPROVING "
            "should outperform, because the cycle turns before the reported "
            "accounts show it. This is a test of the lens as much as of the idea."
        ),
        "horizon": "medium",
        "expected_trade_frequency": "moderate — 30-50 trades a year",
        "expected_holding_period": "a quarter or two",
        "predicted_performance": (
            "Genuinely uncertain, and the most likely of the twelve to be flat. "
            "The cycle lens applies to only four or five sectors, so the effective "
            "universe is small and the sample will be thin for years. A null "
            "result here is informative: it would say the cycle lens is not "
            "predictive, which is worth knowing."
        ),
        "encoding_deviations": (
            "No source. Uses the change in a sector's median ABSOLUTE cycle score "
            "between consecutive scoring dates — absolute, because the relative "
            "median is a within-sector percentile and sits at 50 by construction. "
            "Restricted to the sectors where the cycle lens applies at all; on a "
            "consumer staples company the lens is noise dressed as signal and "
            "Prism declines to score it."
        ),
        "rules": {
            "universe": {
                "min_market_cap": MID_CAP,
                "sectors": ["semiconductors", "hardware", "materials", "energy",
                            "industrials", "commodities"],
            },
            "entry": {
                "kind": "all",
                "conditions": [
                    {"kind": "compare", "id": "sector_cycle_improving",
                     "feature": "sector:cycle_median_delta", "op": "gt", "value": 0},
                    {"kind": "compare", "id": "company_cycle_not_terrible",
                     "feature": "lens:cycle", "op": "gte", "value": 40},
                ],
            },
            "rank": {
                "kind": "rank_sum",
                "components": [
                    {"feature": "sector:cycle_median_delta", "direction": "desc"},
                    {"feature": "lens:cycle", "direction": "desc"},
                ],
                "top_n": 15,
            },
            "rebalance": {"frequency": "monthly", "mode": "reconstitute"},
            "sizing": {"max_positions": 15},
        },
    },
    # ------------------------------------------------------------------ 12
    {
        "name": "Dispersion resolved by trend",
        "authority": "Prism house strategy, 2026-08-13 — experimental",
        "citation": None,
        "hypothesis": (
            "Prism's headline sorting measure is dispersion: how much the six "
            "lenses disagree about the same company. Disagreement marks an "
            "unresolved question. The hypothesis is that when the lenses disagree "
            "AND the price is already trending up, the market is resolving the "
            "disagreement in the optimistic direction, and following the price is "
            "the better side of the bet. Explicitly experimental: this is the one "
            "entrant with no authority behind it whatsoever."
        ),
        "horizon": "medium",
        "expected_trade_frequency": "moderate — 40-60 trades a year",
        "expected_holding_period": "months",
        "predicted_performance": (
            "Most likely to fail of the twelve, and deliberately included anyway. "
            "It is Prism's own idea, so it has never been scrutinised by anyone "
            "else, and the dispersion measure has only existed for months. If it "
            "shows a strong backtest, suspect the backtest before believing the "
            "idea."
        ),
        "encoding_deviations": (
            "No source. Dispersion is Prism's own construct — the gap between the "
            "highest and lowest usable lens score — and only exists from the date "
            "lens scoring began, so the effective history is far shorter than for "
            "the price-based entrants. The backtest window will be correspondingly "
            "thin and the deflation bar should be read accordingly."
        ),
        "rules": {
            "universe": {"min_market_cap": MID_CAP},
            "entry": {
                "kind": "all",
                "conditions": [
                    {"kind": "percentile", "id": "top_quartile_disagreement",
                     "feature": "special:dispersion", "op": "gte", "value": 75},
                    {"kind": "compare", "id": "trend_confirms",
                     "feature": "lens:trend", "op": "gte", "value": 60},
                    {"kind": "compare", "id": "above_200dma",
                     "feature": "price:price_vs_ma200", "op": "gt", "value": 0},
                ],
            },
            "rank": {"components": [{"feature": "special:dispersion", "direction": "desc"}],
                     "top_n": 15},
            "rebalance": {"frequency": "monthly", "mode": "reconstitute"},
            "sizing": {"max_positions": 15},
        },
    },
]


def entries() -> list[dict]:
    """The catalogue with decay notes attached.

    House strategies get a harsher note than published ones: an idea nobody
    else has ever tested is weaker evidence, not stronger.
    """
    out = []
    for entry in CATALOGUE:
        card = dict(entry)
        published = entry["citation"] is not None and "Prism house" not in entry["authority"]
        card["decay_note"] = (
            DEFAULT_DECAY_NOTE if published else _own_idea_decay(DEFAULT_DECAY_NOTE)
        )
        out.append(card)
    return out
