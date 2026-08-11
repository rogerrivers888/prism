"""Shared scoring primitives. Everything here is pure — no database access.

Scores are 0-100 and higher is always better *for that lens's thesis*: a high
value score means cheap, a high cycle score means a favourable point in the
cycle. Comparing scores across lenses is meaningful only through dispersion.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from statistics import fmean

# Bump when a formula changes meaning. Old rows keep their old version rather
# than being recomputed into something different under the same name.
#
# v2: quality gains gross_profitability (Novy-Marx) as a scored input and
#     demotes gross_margin to display-only, which changes both the quality
#     score and its coverage denominator; cycle gains days_inventory_change,
#     derived from history, which changes the cycle score and denominator.
SCORING_VERSION = "v2"

# A percentile against fewer peers than this is noise, so fall back to the
# lens's declared absolute bands instead.
MIN_PEERS = 8

# Below this fraction of declared inputs the score is withheld entirely: a
# score built on two of five metrics looks exactly as confident as one built
# on five, which makes it worse than no score at all.
MIN_COVERAGE = 0.5

METHOD_PERCENTILE = "peer_percentile"
METHOD_BANDS = "absolute_bands"


@dataclass(frozen=True)
class MetricSpec:
    """One declared input to a lens.

    ``bands`` maps raw value to score directly and therefore already encodes
    direction; ``higher_is_better`` orients the peer-percentile path. The two
    must agree, which ``validate_bands`` checks (and a test enforces).
    """

    name: str
    higher_is_better: bool
    bands: tuple[tuple[float, float], ...]
    description: str = ""
    # Built from enterprise value or EBITDA, and therefore undefined for
    # financials. Declared on the metric rather than matched by name, so a
    # new EV or EBITDA ratio is guarded by its own declaration.
    ev_or_ebitda_derived: bool = False
    # Display-only metrics (scored=False) are fetched, stored and returned so
    # the UI can show them, but take no part in the score or the coverage
    # denominator. For figures that are informative to a reader yet unfair to
    # rank — typically because they vary by industry structure rather than by
    # how good the business is. Their band table is inert while scored=False.
    scored: bool = True


@dataclass(frozen=True)
class Lens:
    name: str
    metrics: tuple[MetricSpec, ...]
    applies_to: Callable[[str], bool]
    combine: Callable[[Mapping[str, float]], float]

    @property
    def scored_metrics(self) -> tuple[MetricSpec, ...]:
        return tuple(m for m in self.metrics if m.scored)

    @property
    def declared(self) -> tuple[str, ...]:
        """Names that count towards coverage — display-only metrics do not."""
        return tuple(m.name for m in self.scored_metrics)

    @property
    def display_only(self) -> tuple[str, ...]:
        return tuple(m.name for m in self.metrics if not m.scored)


def validate_bands(spec: MetricSpec) -> None:
    """Bands must be ascending in value and monotonic in the declared direction."""
    values = [v for v, _ in spec.bands]
    if values != sorted(values) or len(set(values)) != len(values):
        raise ValueError(f"{spec.name}: bands must be strictly ascending by value")
    scores = [s for _, s in spec.bands]
    if any(s < 0 or s > 100 for s in scores):
        raise ValueError(f"{spec.name}: band scores must be within 0-100")
    ordered = scores == sorted(scores) if spec.higher_is_better else scores == sorted(
        scores, reverse=True
    )
    if not ordered:
        direction = "rise" if spec.higher_is_better else "fall"
        raise ValueError(
            f"{spec.name}: band scores must {direction} with value to match "
            f"higher_is_better={spec.higher_is_better}"
        )


def band_score(spec: MetricSpec, value: float) -> float:
    """Piecewise-linear interpolation across the declared bands, clamped."""
    bands = spec.bands
    if value <= bands[0][0]:
        return float(bands[0][1])
    if value >= bands[-1][0]:
        return float(bands[-1][1])
    for (lo_v, lo_s), (hi_v, hi_s) in zip(bands, bands[1:]):
        if lo_v <= value <= hi_v:
            span = hi_v - lo_v
            weight = 0.0 if span == 0 else (value - lo_v) / span
            return float(lo_s + weight * (hi_s - lo_s))
    return float(bands[-1][1])  # unreachable, guarded above


def percentile_score(
    spec: MetricSpec, value: float, peers: Sequence[float]
) -> float:
    """Mid-rank percentile of ``value`` within ``peers`` (which includes self).

    Ties split the difference, so identical values never receive different
    scores depending on ordering.
    """
    n = len(peers)
    below = sum(1 for p in peers if p < value)
    equal = sum(1 for p in peers if p == value)
    pct = (below + 0.5 * equal) / n * 100.0
    return pct if spec.higher_is_better else 100.0 - pct


def mean_of_available(subscores: Mapping[str, float]) -> float:
    """Equal-weight mean of whichever declared inputs survived.

    Equal weighting is deliberate: any other weighting is a claim about
    relative importance that we have no evidence for yet.
    """
    return fmean(subscores.values())


@dataclass
class MetricOutcome:
    """What happened to one declared input, for the audit trail."""

    value: float | None = None
    score: float | None = None
    method: str | None = None
    peer_count: int | None = None
    excluded: str | None = None
    scored: bool = True

    def as_dict(self) -> dict:
        return {
            "value": self.value,
            "score": None if self.score is None else round(self.score, 4),
            "method": self.method,
            "peer_count": self.peer_count,
            "excluded": self.excluded,
            "scored": self.scored,
        }


@dataclass
class LensScore:
    """Result of scoring one lens for one ticker on one date."""

    ticker: str
    as_of: object  # datetime.date; kept loose to avoid an import cycle in tests
    lens: str
    score: float | None
    coverage: float
    applicable: bool
    inputs: dict = field(default_factory=dict)
    scoring_version: str = SCORING_VERSION


def usable_scores(scores: Sequence[LensScore]) -> list[float]:
    """Scores that can contribute to dispersion.

    A lens must be applicable *and* have produced a score: an applicable lens
    whose coverage was too thin carries no information about disagreement, so
    it can neither widen nor narrow the spread.
    """
    return [s.score for s in scores if s.applicable and s.score is not None]


def dispersion(scores: Sequence[LensScore]) -> float | None:
    """Spread between the most and least favourable applicable lens.

    Where the methodologies disagree is the headline: a stock every lens likes
    is a consensus trade, a stock they violently disagree about is a research
    question. NULL below three usable readings — a gap between two lenses is a
    coin toss, not a disagreement worth acting on.

    Only lenses that are applicable *and* produced a score can contribute; an
    applicable lens whose coverage was too thin carries no information about
    disagreement, so it cannot widen or narrow the spread.
    """
    usable = usable_scores(scores)
    if len(usable) < 3:
        return None
    return round(max(usable) - min(usable), 4)
