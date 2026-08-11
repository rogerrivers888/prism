"""Currency identity rules.

No conversion happens here and no FX layer exists yet. The single job of this
module is to make one specific trap impossible to step in silently: some
exchanges quote in a *minor unit*. London quotes many shares in GBX (pence),
which is one hundredth of GBP. A GBX price added to, compared with, or
displayed as GBP is wrong by a factor of 100 — and it looks entirely
plausible, which is what makes it dangerous.

So: GBX is never equal to GBP. Anything that needs to combine the two must
say so explicitly and will get an exception until the FX and unit layer is
built deliberately.
"""

# Quote currencies that are a fraction of a settlement currency.
# code -> (major currency, units per major)
MINOR_UNITS: dict[str, tuple[str, int]] = {
    "GBX": ("GBP", 100),  # London pence
    "GBp": ("GBP", 100),  # same thing, lower-case variant seen in the wild
    "ZAC": ("ZAR", 100),  # Johannesburg cents
    "ILA": ("ILS", 100),  # Tel Aviv agorot
}


class CurrencyMismatch(Exception):
    """Two amounts are not in the same currency and cannot be combined."""


def is_minor_unit(code: str | None) -> bool:
    return bool(code) and code in MINOR_UNITS


def major_unit_of(code: str | None) -> str | None:
    """The settlement currency a minor unit belongs to, if any.

    Knowing GBX belongs to GBP is NOT permission to treat them as equal —
    it is what lets an error message explain the difference.
    """
    if not code:
        return None
    pair = MINOR_UNITS.get(code)
    return pair[0] if pair else None


def same_currency(left: str | None, right: str | None) -> bool:
    """Strict equality. GBX and GBP are different currencies here, deliberately."""
    return left is not None and right is not None and left == right


def require_same_currency(left: str | None, right: str | None) -> str:
    """Return the shared currency, or raise explaining the mismatch."""
    if same_currency(left, right):
        return left  # type: ignore[return-value]
    hint = ""
    if major_unit_of(left) == right or major_unit_of(right) == left:
        hint = (
            f" — {left} and {right} differ by a factor of 100; converting minor "
            "units is deliberate work, not an implicit cast"
        )
    raise CurrencyMismatch(f"cannot combine {left} with {right}{hint}")
