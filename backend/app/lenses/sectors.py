"""Sector taxonomy and the structural classifications scoring depends on.

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
        "banks",
        "insurance",
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
#
# Known limitation: biotech is genuinely asset-light — its value is in a
# pipeline, not a balance sheet — but it sits inside "healthcare" alongside
# pharma and medical devices, which are asset-heavy (plant, inventory, real
# book value). We cannot distinguish the subsector today, so healthcare is
# treated as asset-heavy and biotech P/B readings will be misleadingly high.
# Revisit when the securities table carries a subsector.
ASSET_LIGHT_SECTORS = frozenset({"software", "communication_services"})

# Banks fund themselves with deposits, so debt is raw material rather than
# leverage, and EBITDA is not a meaningful earnings measure when interest is
# the revenue line. Enterprise-value and EBITDA-derived ratios here are not
# merely inaccurate, they are undefined. P/B is the opposite case: for
# financials it is one of the *more* meaningful value metrics, so it stays.
FINANCIALS_SECTORS = frozenset({"financials", "banks", "insurance"})


def is_cyclical(sector: str) -> bool:
    return sector in CYCLICAL_SECTORS


def is_asset_light(sector: str) -> bool:
    return sector in ASSET_LIGHT_SECTORS


def is_financial(sector: str) -> bool:
    return sector in FINANCIALS_SECTORS
