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
        exchange = entry.get("Exchange") or suffix
        # EODHD reports US listings under their venue (NYSE/NASDAQ) but
        # addresses them with the .US suffix.
        routing = "US" if exchange in ("NYSE", "NASDAQ", "NYSE ARCA", "BATS") else exchange
        tickers.append(f"{code}.{routing}")
    return tickers


def combine(*groups: object) -> list[str]:
    """Union of ticker groups, order-stable and de-duplicated."""
    seen: dict[str, None] = {}
    for group in groups:
        for ticker in group:  # type: ignore[union-attr]
            seen.setdefault(ticker, None)
    return list(seen)
