"""Quality lens: does the business earn good returns and survive bad years?

High score = higher returns on capital, fatter margins, less fragile balance
sheet. Bands are initial judgement calls and want review.
"""

from app.lenses.base import Lens, MetricSpec, mean_of_available

METRICS = (
    MetricSpec(
        name="roic",
        higher_is_better=True,
        bands=((0, 0), (4, 15), (8, 35), (12, 52), (16, 68), (22, 84), (30, 100)),
        description="Return on invested capital, percent",
    ),
    MetricSpec(
        name="gross_margin",
        higher_is_better=True,
        bands=((10, 0), (20, 20), (30, 38), (40, 55), (50, 70), (65, 88), (80, 100)),
        description="Gross margin, percent",
    ),
    MetricSpec(
        name="net_debt_to_ebitda",
        higher_is_better=False,
        bands=((-1, 100), (0, 92), (1, 78), (2, 60), (3, 42), (4.5, 22), (6, 0)),
        description="Net debt / EBITDA; negative means net cash",
    ),
    MetricSpec(
        name="interest_cover",
        higher_is_better=True,
        bands=((1, 0), (2, 20), (4, 42), (7, 60), (12, 78), (20, 92), (35, 100)),
        description="EBIT / interest expense, times",
    ),
    MetricSpec(
        name="fcf_conversion",
        higher_is_better=True,
        bands=((0, 0), (25, 20), (50, 40), (75, 58), (95, 75), (120, 90), (150, 100)),
        description="Free cash flow / net income, percent",
    ),
)


def applies_to(sector: str) -> bool:
    return True


LENS = Lens(
    name="quality",
    metrics=METRICS,
    applies_to=applies_to,
    combine=mean_of_available,
)
