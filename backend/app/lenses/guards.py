"""Metric validity guards.

A metric that is arithmetically computable but economically meaningless is
worse than a missing one, because it scores like a real reading. Guards
exclude such metrics; exclusion reduces coverage rather than scoring zero,
since "we cannot measure this" is not the same as "this is bad".

Where the distinction needs judgement we do not guess — we exclude and raise
a flag for a human to classify.
"""

from collections.abc import Mapping

from app.lenses.sectors import is_asset_light

# Raised when a metric is unusable for a reason a human should look at.
FLAG_FCF_NEEDS_CLASSIFICATION = "fcf_negative_requires_classification"
FLAG_EBITDA_UNKNOWN = "ebitda_unknown_ev_ebitda_unverified"


def check(metric: str, sector: str, metrics: Mapping[str, float]) -> str | None:
    """Return an exclusion reason for ``metric``, or None if it is usable."""
    if metric == "ev_ebitda":
        ebitda = metrics.get("ebitda")
        # A negative or zero denominator makes the multiple meaningless — a
        # loss-making company can print an attractive-looking figure.
        if ebitda is not None and ebitda <= 0:
            return "ebitda_non_positive"
        return None

    if metric == "price_to_book":
        # Book value understates asset-light businesses so badly that a high
        # P/B carries no information about expensiveness.
        if is_asset_light(sector):
            return "asset_light_sector"
        return None

    if metric == "fcf_yield":
        fcf = metrics.get("fcf")
        if fcf is not None and fcf < 0:
            # Negative FCF is disqualifying if structural and potentially
            # bullish if cyclical (a capex build-out). We cannot tell which
            # from the number alone, so we exclude and flag rather than guess.
            return "fcf_negative_unclassified"
        return None

    return None


def flags(sector: str, metrics: Mapping[str, float]) -> list[str]:
    """Conditions a human should resolve, surfaced in the audit trail."""
    raised: list[str] = []
    fcf = metrics.get("fcf")
    if fcf is not None and fcf < 0:
        raised.append(FLAG_FCF_NEEDS_CLASSIFICATION)
    if "ev_ebitda" in metrics and metrics.get("ebitda") is None:
        # We could not verify the denominator, so the multiple is taken on
        # trust. Visible in the audit trail rather than silently accepted.
        raised.append(FLAG_EBITDA_UNKNOWN)
    return raised
