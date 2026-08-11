"""Trend lens: where is price relative to its own recent structure?

High score = price above its moving averages with the averages themselves
rising. Bands are initial judgement calls and want review.
"""

from app.lenses.base import Lens, MetricSpec, mean_of_available

METRICS = (
    MetricSpec(
        name="price_vs_50dma",
        higher_is_better=True,
        bands=(
            (-20, 0), (-10, 18), (-3, 38), (0, 50), (3, 62), (8, 80), (15, 95), (25, 100)
        ),
        description="Price vs 50-day moving average, percent",
    ),
    MetricSpec(
        name="price_vs_200dma",
        higher_is_better=True,
        bands=(
            (-30, 0), (-15, 18), (-5, 38), (0, 50), (5, 62), (12, 78), (25, 93), (40, 100)
        ),
        description="Price vs 200-day moving average, percent",
    ),
    MetricSpec(
        name="ma50_vs_ma200",
        higher_is_better=True,
        bands=(
            (-15, 0), (-7, 20), (-2, 40), (0, 50), (2, 60), (6, 78), (12, 92), (20, 100)
        ),
        description="50-day vs 200-day moving average, percent",
    ),
    MetricSpec(
        name="pct_above_52w_low",
        higher_is_better=True,
        bands=((0, 0), (10, 20), (25, 38), (40, 52), (60, 68), (90, 85), (130, 100)),
        description="Distance above the 52-week low, percent",
    ),
)


def applies_to(sector: str) -> bool:
    """Price structure exists for anything that trades."""
    return True


LENS = Lens(
    name="trend",
    metrics=METRICS,
    applies_to=applies_to,
    combine=mean_of_available,
)
