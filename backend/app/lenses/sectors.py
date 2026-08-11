"""Sector taxonomy and the two structural classifications scoring depends on.

These are judgement calls about business models, not data — they live here so
they are reviewable in one place rather than scattered through the lenses.
"""

SECTORS = frozenset(
    {
        "semiconductors",
        "hardware",
        "commodities",
        "materials",
        "energy",
        "industrials",
        "consumer_discretionary",
        "consumer_staples",
        "healthcare",
        "financials",
        "software",
        "communication_services",
        "utilities",
        "real_estate",
    }
)

# Cycle only means something where inventory and pricing actually cycle.
# A Cycle reading on a consumer staples company is noise dressed as signal.
CYCLICAL_SECTORS = frozenset({"semiconductors", "hardware", "commodities"})

# Book value is close to meaningless where the productive assets are
# intangible, so P/B is excluded rather than scored.
ASSET_LIGHT_SECTORS = frozenset({"software", "communication_services", "healthcare"})


def is_cyclical(sector: str) -> bool:
    return sector in CYCLICAL_SECTORS


def is_asset_light(sector: str) -> bool:
    return sector in ASSET_LIGHT_SECTORS
