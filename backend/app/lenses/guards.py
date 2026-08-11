"""Metric validity guards.

A metric that is arithmetically computable but economically meaningless is
worse than a missing one, because it scores like a real reading. Guards
exclude such metrics; exclusion reduces coverage rather than scoring zero,
since "we cannot measure this" is not the same as "this is bad". If enough
exclusions drop coverage below the minimum the lens returns no score, which
is the correct outcome — we do not reweight the survivors to compensate,
because that would quietly restate a thin reading as a full one.

Where the distinction needs judgement we do not guess — we exclude and raise
a flag for a human to classify.
"""

from collections.abc import Mapping

from app.lenses.base import MetricSpec
from app.lenses.sectors import is_asset_light, is_financial

# Raised when a metric is unusable for a reason a human should look at.
FLAG_FCF_NEEDS_CLASSIFICATION = "fcf_negative_requires_classification"
FLAG_EBITDA_UNKNOWN = "ebitda_unknown_ev_ebitda_unverified"


def check(spec: MetricSpec, sector: str, metrics: Mapping[str, float]) -> str | None:
    """Return an exclusion reason for ``spec``, or None if it is usable."""
    # Sector-structural exclusions first: they hold regardless of the values.
    if spec.ev_or_ebitda_derived and is_financial(sector):
        # Deposits are not leverage and EBITDA is not earnings for a bank;
        # these ratios are undefined here, not just unflattering.
        return "financials_ev_ebitda_undefined"

    if spec.name == "price_to_book":
        if is_asset_light(sector):
            # Book value understates asset-light businesses so badly that a
            # high P/B carries no information about expensiveness.
            return "asset_light_sector"
        # Deliberately kept for financials: book value is close to the real
        # economics there, making P/B one of the better value metrics.
        return None

    if spec.name == "ev_ebitda":
        ebitda = metrics.get("ebitda")
        # A negative or zero denominator makes the multiple meaningless — a
        # loss-making company can print an attractive-looking figure.
        if ebitda is not None and ebitda <= 0:
            return "ebitda_non_positive"
        return None

    if spec.name == "fcf_yield":
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
    if (
        "ev_ebitda" in metrics
        and metrics.get("ebitda") is None
        # For financials the multiple is excluded outright, so an unverified
        # denominator is not worth anyone's attention.
        and not is_financial(sector)
    ):
        # We could not verify the denominator, so the multiple is taken on
        # trust. Visible in the audit trail rather than silently accepted.
        raised.append(FLAG_EBITDA_UNKNOWN)
    return raised
