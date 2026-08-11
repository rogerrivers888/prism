"""The securities Prism tracks.

Index membership is resolved from the provider rather than hard-coded, so the
S&P 500 and NASDAQ-100 stay current. Everything else is an explicit list.
"""

# Roger's UK holdings. LSE names quote in GBX (pence) — see app/currency.py.
UK_HOLDINGS = ("VLX.LSE", "IQE.LSE", "ULVR.LSE")

# The semiconductor complex, wherever it happens to be listed. A real peer
# group here is the whole point: percentiles need eight members with a metric
# before they beat absolute bands.
SEMICONDUCTOR_PEERS = (
    "000660.KO",   # SK Hynix
    "005930.KO",   # Samsung Electronics
    "285A.TSE",    # Kioxia
    "ASML.US",     # ASML
    "AMAT.US",     # Applied Materials
    "LRCX.US",     # Lam Research
    "KLAC.US",     # KLA
    "MRVL.US",     # Marvell
    "AVGO.US",     # Broadcom
    "QCOM.US",     # Qualcomm
    "TXN.US",      # Texas Instruments
    "ADI.US",      # Analog Devices
    "MCHP.US",     # Microchip
    "ON.US",       # onsemi
    "STM.US",      # STMicroelectronics
    "NXPI.US",     # NXP
    # "INFY" in a semiconductor peer list is ambiguous: INFY.US is Infosys, an
    # IT services firm, while the semiconductor company is Infineon
    # (IFX.XETRA). Both are included so the intended one is present; they map
    # to different sectors, so neither pollutes the other's peer group.
    "IFX.XETRA",   # Infineon
    "INFY.US",     # Infosys
)

# Provider symbols for the index constituent lists.
SP500_INDEX = "GSPC.INDX"
NASDAQ100_INDEX = "NDX.INDX"


# Venues EODHD addresses with the .US suffix rather than their own code.
US_VENUES = frozenset(
    {"NYSE", "NASDAQ", "NYSE ARCA", "NYSE MKT", "BATS", "AMEX", "OTC", "OTCMKTS", "NYSE American"}
)


def provider_ticker(symbol: str, exchange: str | None) -> str:
    """Bare symbol plus the routing suffix the provider expects.

    Storage keys on the bare symbol; the suffix is provider addressing. US
    venues all resolve to .US, and every other exchange is addressed by its
    own code — so a venue we have never seen routes correctly rather than
    silently defaulting to .US and 404ing.
    """
    if not exchange or exchange in US_VENUES:
        return f"{symbol}.US"
    return f"{symbol}.{exchange}"


def components_from_index(payload: object, suffix: str = "US") -> list[str]:
    """Extract provider tickers from an index fundamentals payload."""
    if not isinstance(payload, dict):
        return []
    components = payload.get("Components")
    if not isinstance(components, dict):
        return []

    tickers = []
    for entry in components.values():
        if not isinstance(entry, dict):
            continue
        code = entry.get("Code")
        if not code:
            continue
        tickers.append(provider_ticker(code, entry.get("Exchange") or suffix))
    return tickers


def combine(*groups: object) -> list[str]:
    """Union of ticker groups, order-stable and de-duplicated."""
    seen: dict[str, None] = {}
    for group in groups:
        for ticker in group:  # type: ignore[union-attr]
            seen.setdefault(ticker, None)
    return list(seen)
