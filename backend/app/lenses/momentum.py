"""Momentum lens: has it been working, and are estimates going up?

High score = stronger trailing returns and rising earnings revisions. Bands
are initial judgement calls and want review.
"""

from app.lenses.base import Lens, MetricSpec, mean_of_available

METRICS = (
    MetricSpec(
        name="return_3m",
        higher_is_better=True,
        bands=(
            (-30, 0), (-15, 15), (-5, 32), (0, 45), (5, 58), (15, 78), (30, 92), (50, 100)
        ),
        description="Three-month total return, percent",
    ),
    MetricSpec(
        name="return_6m",
        higher_is_better=True,
        bands=(
            (-40, 0), (-20, 15), (-8, 32), (0, 45), (8, 58), (20, 76), (40, 92), (70, 100)
        ),
        description="Six-month total return, percent",
    ),
    MetricSpec(
        name="return_12m",
        higher_is_better=True,
        bands=(
            (-50, 0), (-25, 15), (-10, 32), (0, 45), (10, 58), (25, 75), (50, 90), (90, 100)
        ),
        description="Twelve-month total return, percent",
    ),
    MetricSpec(
        name="earnings_revision_3m",
        higher_is_better=True,
        bands=((-20, 0), (-10, 15), (-3, 35), (0, 50), (3, 65), (8, 82), (15, 100)),
        description="Three-month change in consensus EPS, percent",
    ),
)


def applies_to(sector: str) -> bool:
    return True


LENS = Lens(
    name="momentum",
    metrics=METRICS,
    applies_to=applies_to,
    combine=mean_of_available,
)
