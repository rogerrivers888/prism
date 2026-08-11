"""Cycle lens: where in the inventory and pricing cycle is this business?

Applies only to sectors that genuinely cycle on inventory and pricing —
semiconductors, hardware, commodities. For everything else the lens reports
applicable=false and score=null rather than a number: a Cycle reading on a
consumer staples company is noise dressed as signal.

High score = favourable point in the cycle (lean inventory, tight capacity,
rising prices, orders ahead of shipments). Bands are initial judgement calls
and want review.
"""

from app.lenses.base import Lens, MetricSpec, mean_of_available
from app.lenses.sectors import is_cyclical

METRICS = (
    MetricSpec(
        name="inventory_to_sales",
        higher_is_better=False,
        bands=(
            (0.05, 100), (0.1, 85), (0.15, 68), (0.2, 52), (0.3, 32), (0.45, 12), (0.6, 0)
        ),
        description="Inventory / sales, times",
    ),
    MetricSpec(
        name="days_inventory",
        higher_is_better=False,
        bands=((20, 100), (40, 82), (60, 65), (85, 48), (110, 30), (150, 12), (200, 0)),
        description="Days inventory outstanding — the level",
    ),
    MetricSpec(
        name="days_inventory_change",
        higher_is_better=False,
        bands=((-40, 100), (-20, 88), (-8, 70), (0, 50), (8, 30), (20, 12), (40, 0)),
        description=(
            "Year-on-year change in days inventory, in days. Derived from "
            "fundamentals history, not ingested separately. Sits beside the "
            "level because 94 days falling is bullish and 94 days rising is "
            "bearish — direction carries more information than level"
        ),
    ),
    MetricSpec(
        name="capacity_utilisation",
        higher_is_better=True,
        bands=((50, 0), (60, 18), (70, 38), (78, 55), (85, 72), (92, 88), (97, 100)),
        description="Capacity utilisation, percent",
    ),
    MetricSpec(
        name="asp_change_yoy",
        higher_is_better=True,
        bands=((-25, 0), (-12, 18), (-4, 38), (0, 50), (4, 62), (10, 80), (20, 100)),
        description="Average selling price change year on year, percent",
    ),
    MetricSpec(
        name="book_to_bill",
        higher_is_better=True,
        bands=((0.6, 0), (0.8, 22), (0.9, 38), (1.0, 52), (1.1, 68), (1.25, 86), (1.5, 100)),
        description="Book-to-bill ratio, times",
    ),
)


def applies_to(sector: str) -> bool:
    return is_cyclical(sector)


LENS = Lens(
    name="cycle",
    metrics=METRICS,
    applies_to=applies_to,
    combine=mean_of_available,
)
