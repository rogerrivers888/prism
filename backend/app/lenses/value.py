"""Value lens: is this cheap relative to what it earns and owns?

High score = cheap. Bands are initial judgement calls and want review.
"""

from app.lenses.base import Lens, MetricSpec, mean_of_available

METRICS = (
    MetricSpec(
        name="pe_ratio",
        higher_is_better=False,
        bands=((5, 100), (10, 85), (15, 65), (20, 50), (30, 30), (50, 10), (80, 0)),
        description="Trailing price / earnings",
    ),
    MetricSpec(
        name="ev_ebitda",
        higher_is_better=False,
        bands=((3, 100), (6, 85), (9, 65), (12, 50), (16, 30), (25, 10), (40, 0)),
        description=(
            "Enterprise value / EBITDA; excluded when EBITDA <= 0 and for "
            "financials, where it is undefined"
        ),
        ev_or_ebitda_derived=True,
    ),
    MetricSpec(
        name="fcf_yield",
        higher_is_better=True,
        bands=((-5, 0), (0, 10), (2, 35), (4, 55), (6, 72), (9, 88), (15, 100)),
        description="Free cash flow / market cap, percent",
    ),
    MetricSpec(
        name="price_to_book",
        higher_is_better=False,
        bands=((0.5, 100), (1, 85), (1.5, 70), (2.5, 50), (4, 30), (7, 12), (12, 0)),
        description=(
            "Price / book; excluded for asset-light sectors, kept for "
            "financials where book value is close to the real economics"
        ),
    ),
    MetricSpec(
        name="dividend_yield",
        higher_is_better=True,
        bands=((0, 10), (1, 30), (2, 45), (3, 60), (4, 72), (6, 88), (9, 100)),
        description="Trailing dividend yield, percent",
    ),
)


def applies_to(sector: str) -> bool:
    """Cheapness is a question worth asking of any business."""
    return True


LENS = Lens(
    name="value",
    metrics=METRICS,
    applies_to=applies_to,
    combine=mean_of_available,
)
