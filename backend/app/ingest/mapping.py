"""Provider classification strings mapped onto Prism's sector taxonomy.

EODHD gives a coarse ``Sector`` ("Technology") and a finer ``Industry``
("Semiconductors"). Our taxonomy cares about structural properties — does it
cycle on inventory, is it asset-light, is it a deposit-funded lender — which
track Industry far more closely than Sector, so Industry is consulted first.

Every string below was observed in the provider's own responses, not guessed.
An earlier version guessed em-dashes ("Insurance—Life"); EODHD uses a spaced
hyphen ("Insurance - Life"), so none of those keys could ever match and every
financial fell through to the coarse sector.

Unmapped classifications still fall back on the coarse sector, and anything
unrecognised raises rather than being silently bucketed: a wrong sector
silently changes Cycle applicability and the P/B guard.
"""

import logging

logger = logging.getLogger(__name__)

# EODHD Industry -> Prism sector.
INDUSTRY_TO_SECTOR = {
    # Departed constituents sometimes return with a different upstream
    # taxonomy; these two appeared on recovered names.
    "Investment Banking & Investment Services": "financials",
    "Auto Components": "consumer_discretionary",
    # --- semiconductors: the cycle lens applies here ---
    "Semiconductors": "semiconductors",
    "Semiconductor Equipment & Materials": "semiconductors",
    # --- hardware: asset-heavy manufacturing, also cyclical ---
    "Computer Hardware": "hardware",
    "Consumer Electronics": "hardware",
    "Communication Equipment": "hardware",
    "Electronic Components": "hardware",
    "Electronics & Computer Distribution": "hardware",
    # Instrument makers own plant and inventory. Left to the coarse
    # "Technology" fallback they landed in software, which is asset-light,
    # and had P/B excluded — the exact opposite of what that guard is for.
    "Scientific & Technical Instruments": "hardware",
    "Solar": "hardware",
    # --- software and IT services: genuinely asset-light ---
    "Software": "software",
    "Software - Application": "software",
    "Software - Infrastructure": "software",
    "Information Technology Services": "software",
    # --- communication services ---
    "Internet Content & Information": "communication_services",
    "Telecom Services": "communication_services",
    "Entertainment": "communication_services",
    "Broadcasting": "communication_services",
    "Advertising Agencies": "communication_services",
    "Electronic Gaming & Multimedia": "communication_services",
    "Publishing": "communication_services",
    # --- energy ---
    "Oil & Gas Integrated": "energy",
    "Oil & Gas E&P": "energy",
    "Oil & Gas Equipment & Services": "energy",
    "Oil & Gas Midstream": "energy",
    "Oil & Gas Refining & Marketing": "energy",
    "Oil & Gas Drilling": "energy",
    "Thermal Coal": "energy",
    "Uranium": "energy",
    # --- commodities: priced off a global clearing price, so they cycle ---
    "Gold": "commodities",
    "Silver": "commodities",
    "Copper": "commodities",
    "Steel": "commodities",
    "Aluminum": "commodities",
    "Other Industrial Metals & Mining": "commodities",
    "Other Precious Metals & Mining": "commodities",
    "Coking Coal": "commodities",
    # --- materials: processed, not clearing-price commodities ---
    "Specialty Chemicals": "materials",
    "Chemicals": "materials",
    "Agricultural Inputs": "materials",
    "Building Materials": "materials",
    "Packaging & Containers": "materials",
    "Paper & Paper Products": "materials",
    "Lumber & Wood Production": "materials",
    # --- industrials ---
    "Aerospace & Defense": "industrials",
    "Airlines": "industrials",
    "Railroads": "industrials",
    "Trucking": "industrials",
    "Integrated Freight & Logistics": "industrials",
    "Marine Shipping": "industrials",
    "Building Products & Equipment": "industrials",
    "Engineering & Construction": "industrials",
    "Infrastructure Operations": "industrials",
    "Conglomerates": "industrials",
    "Consulting Services": "industrials",
    "Specialty Business Services": "industrials",
    "Staffing & Employment Services": "industrials",
    "Industrial Distribution": "industrials",
    "Specialty Industrial Machinery": "industrials",
    "Farm & Heavy Construction Machinery": "industrials",
    "Metal Fabrication": "industrials",
    "Tools & Accessories": "industrials",
    "Electrical Equipment & Parts": "industrials",
    "Pollution & Treatment Controls": "industrials",
    "Security & Protection Services": "industrials",
    "Rental & Leasing Services": "industrials",
    "Waste Management": "industrials",
    "Airports & Air Services": "industrials",
    "Business Equipment & Supplies": "industrials",
    # --- consumer discretionary ---
    "Auto Manufacturers": "consumer_discretionary",
    "Auto Parts": "consumer_discretionary",
    "Auto & Truck Dealerships": "consumer_discretionary",
    "Recreational Vehicles": "consumer_discretionary",
    "Apparel Manufacturing": "consumer_discretionary",
    "Apparel Retail": "consumer_discretionary",
    "Footwear & Accessories": "consumer_discretionary",
    "Luxury Goods": "consumer_discretionary",
    "Home Improvement Retail": "consumer_discretionary",
    "Specialty Retail": "consumer_discretionary",
    "Internet Retail": "consumer_discretionary",
    "Department Stores": "consumer_discretionary",
    "Furnishings, Fixtures & Appliances": "consumer_discretionary",
    "Residential Construction": "consumer_discretionary",
    "Restaurants": "consumer_discretionary",
    "Lodging": "consumer_discretionary",
    "Resorts & Casinos": "consumer_discretionary",
    "Travel Services": "consumer_discretionary",
    "Leisure": "consumer_discretionary",
    "Gambling": "consumer_discretionary",
    "Personal Services": "consumer_discretionary",
    "Education & Training Services": "consumer_discretionary",
    # --- consumer staples ---
    "Beverages - Brewers": "consumer_staples",
    "Beverages - Wineries & Distilleries": "consumer_staples",
    "Beverages - Non-Alcoholic": "consumer_staples",
    "Packaged Foods": "consumer_staples",
    "Confectioners": "consumer_staples",
    "Farm Products": "consumer_staples",
    "Food Distribution": "consumer_staples",
    "Grocery Stores": "consumer_staples",
    "Discount Stores": "consumer_staples",
    "Household & Personal Products": "consumer_staples",
    "Tobacco": "consumer_staples",
    # --- healthcare ---
    "Biotechnology": "healthcare",
    "Drug Manufacturers - General": "healthcare",
    "Drug Manufacturers - Specialty & Generic": "healthcare",
    "Medical Devices": "healthcare",
    "Medical Instruments & Supplies": "healthcare",
    "Medical Distribution": "healthcare",
    "Medical Care Facilities": "healthcare",
    "Diagnostics & Research": "healthcare",
    "Healthcare Plans": "healthcare",
    "Health Information Services": "healthcare",
    "Pharmaceutical Retailers": "healthcare",
    # --- banks: deposit-funded, so EV and EBITDA ratios are undefined ---
    "Banks - Diversified": "banks",
    "Banks - Regional": "banks",
    "Mortgage Finance": "banks",
    # --- insurance ---
    "Insurance - Diversified": "insurance",
    "Insurance - Life": "insurance",
    "Insurance - Property & Casualty": "insurance",
    "Insurance - Reinsurance": "insurance",
    "Insurance - Specialty": "insurance",
    "Insurance Brokers": "insurance",
    # --- other financials ---
    "Asset Management": "financials",
    "Capital Markets": "financials",
    "Credit Services": "financials",
    "Financial Data & Stock Exchanges": "financials",
    "Financial Conglomerates": "financials",
    "Shell Companies": "financials",
    # --- utilities ---
    "Utilities - Regulated Electric": "utilities",
    "Utilities - Regulated Gas": "utilities",
    "Utilities - Regulated Water": "utilities",
    "Utilities - Diversified": "utilities",
    "Utilities - Independent Power Producers": "utilities",
    "Utilities - Renewable": "utilities",
    # --- real estate ---
    "Real Estate Services": "real_estate",
    "Real Estate - Development": "real_estate",
    "Real Estate - Diversified": "real_estate",
    "REIT - Diversified": "real_estate",
    "REIT - Healthcare Facilities": "real_estate",
    "REIT - Hotel & Motel": "real_estate",
    "REIT - Industrial": "real_estate",
    "REIT - Mortgage": "real_estate",
    "REIT - Office": "real_estate",
    "REIT - Residential": "real_estate",
    "REIT - Retail": "real_estate",
    "REIT - Specialty": "real_estate",
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
    if (provider_sector, provider_industry) == (None, None) or (
        provider_sector == "Other" and provider_industry == "Other"
    ):
        # Delisted companies frequently lose their classification upstream and
        # come back as Other/Other. "unclassified" is the honest answer: these
        # names never match a sector-restricted strategy and never join a peer
        # group, but their prices and fundamentals still repair the
        # survivorship hole. Not a guess — a declared absence.
        return "unclassified"
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
