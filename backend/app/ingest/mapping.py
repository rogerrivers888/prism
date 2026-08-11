"""Provider classification strings mapped onto Prism's sector taxonomy.

EODHD gives a coarse ``Sector`` ("Technology") and a finer ``Industry``
("Semiconductors"). Our taxonomy cares about structural properties — does it
cycle on inventory, is it asset-light, is it a deposit-funded lender — which
track Industry far more closely than Sector, so Industry is consulted first.

Unmapped classifications fall back on the coarse sector, and anything still
unrecognised raises rather than being silently bucketed: a wrong sector
silently changes Cycle applicability and the P/B guard.
"""

import logging

logger = logging.getLogger(__name__)

# EODHD Industry -> Prism sector. Industry strings observed from the provider.
INDUSTRY_TO_SECTOR = {
    "Semiconductors": "semiconductors",
    "Semiconductor Equipment & Materials": "semiconductors",
    "Computer Hardware": "hardware",
    "Consumer Electronics": "hardware",
    "Communication Equipment": "hardware",
    "Electronic Components": "hardware",
    "Software—Infrastructure": "software",
    "Software—Application": "software",
    "Information Technology Services": "software",
    "Internet Content & Information": "communication_services",
    "Telecom Services": "communication_services",
    "Entertainment": "communication_services",
    "Oil & Gas Integrated": "energy",
    "Oil & Gas E&P": "energy",
    "Gold": "commodities",
    "Copper": "commodities",
    "Steel": "commodities",
    "Other Industrial Metals & Mining": "commodities",
    "Aluminum": "commodities",
    "Specialty Chemicals": "materials",
    "Chemicals": "materials",
    "Banks—Diversified": "banks",
    "Banks—Regional": "banks",
    "Insurance—Diversified": "insurance",
    "Insurance—Property & Casualty": "insurance",
    "Insurance—Life": "insurance",
    "Asset Management": "financials",
    "Capital Markets": "financials",
    "Biotechnology": "healthcare",
    "Drug Manufacturers—General": "healthcare",
    "Medical Devices": "healthcare",
}

# EODHD Sector -> Prism sector, used when the Industry is unrecognised.
SECTOR_TO_SECTOR = {
    "Technology": "software",
    "Communication Services": "communication_services",
    "Energy": "energy",
    "Basic Materials": "materials",
    "Industrials": "industrials",
    "Consumer Cyclical": "consumer_discretionary",
    "Consumer Defensive": "consumer_staples",
    "Healthcare": "healthcare",
    "Financial Services": "financials",
    "Financial": "financials",
    "Utilities": "utilities",
    "Real Estate": "real_estate",
}


class UnmappedSector(Exception):
    """Provider classification we have no mapping for."""


def map_sector(provider_sector: str | None, provider_industry: str | None) -> str:
    """Resolve a Prism sector, preferring the finer Industry string."""
    if provider_industry and provider_industry in INDUSTRY_TO_SECTOR:
        return INDUSTRY_TO_SECTOR[provider_industry]
    if provider_sector and provider_sector in SECTOR_TO_SECTOR:
        mapped = SECTOR_TO_SECTOR[provider_sector]
        logger.warning(
            "industry %r unmapped, falling back to sector %r -> %s",
            provider_industry,
            provider_sector,
            mapped,
        )
        return mapped
    raise UnmappedSector(
        f"no mapping for sector={provider_sector!r} industry={provider_industry!r}; "
        "add it to app/ingest/mapping.py rather than guessing"
    )
