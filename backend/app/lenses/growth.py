"""Growth lens: is the business getting bigger, and at what rate?

High score = growing faster. Bands are initial judgement calls and want review.
"""

from app.lenses.base import Lens, MetricSpec, mean_of_available

METRICS = (
    MetricSpec(
        name="revenue_growth_yoy",
        higher_is_better=True,
        bands=(
            (-20, 0), (-5, 15), (0, 25), (5, 40), (10, 55), (20, 75), (35, 90), (60, 100)
        ),
        description="Year-on-year revenue growth, percent",
    ),
    MetricSpec(
        name="eps_growth_yoy",
        higher_is_better=True,
        bands=(
            (-30, 0), (-10, 15), (0, 25), (8, 45), (15, 60), (25, 78), (40, 90), (70, 100)
        ),
        description="Year-on-year EPS growth, percent",
    ),
    MetricSpec(
        name="revenue_cagr_3y",
        higher_is_better=True,
        bands=((-10, 0), (0, 20), (4, 40), (8, 58), (14, 75), (22, 90), (35, 100)),
        description="Three-year revenue CAGR, percent",
    ),
    MetricSpec(
        name="eps_cagr_3y",
        higher_is_better=True,
        bands=((-15, 0), (0, 20), (5, 40), (10, 58), (16, 75), (25, 90), (40, 100)),
        description="Three-year EPS CAGR, percent",
    ),
    MetricSpec(
        name="fcf_growth_yoy",
        higher_is_better=True,
        bands=((-40, 0), (-10, 20), (0, 32), (10, 52), (20, 68), (35, 85), (60, 100)),
        description="Year-on-year free cash flow growth, percent",
    ),
)


def applies_to(sector: str) -> bool:
    return True


LENS = Lens(
    name="growth",
    metrics=METRICS,
    applies_to=applies_to,
    combine=mean_of_available,
)
