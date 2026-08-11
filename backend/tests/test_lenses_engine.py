"""Database-backed lens tests: point-in-time correctness and persistence."""

from datetime import date

import pytest

from app.lenses.base import SCORING_VERSION
from app.lenses.engine import score_ticker, score_universe, stored_scores
from tests import fixtures

PERIOD = date(2026, 3, 31)


@pytest.fixture(autouse=True)
async def clean_market_data(session):
    await fixtures.clean(session)
    yield
    await session.rollback()


def _lens(scores, name):
    return next(s for s in scores if s.lens == name)


async def test_metric_published_after_as_of_is_invisible(session):
    # Published 1 May; scoring on 30 April must not see it.
    await fixtures.add_company(
        session, "LATE", "industrials", published_at=date(2026, 5, 1)
    )
    await session.flush()

    before = await score_ticker(session, "LATE", date(2026, 4, 30))
    after = await score_ticker(session, "LATE", date(2026, 5, 1))

    assert _lens(before, "value").coverage == 0.0
    assert _lens(before, "value").score is None
    assert _lens(after, "value").score is not None


async def test_restatement_changes_scores_only_from_its_published_at(session):
    await fixtures.add_company(
        session,
        "REST",
        "industrials",
        dict(fixtures.BASELINE, roic=6.0),
        published_at=date(2026, 5, 1),
    )
    # Same period restated upward, disclosed a month later.
    await fixtures.add_metrics(
        session,
        "REST",
        {"roic": 24.0},
        published_at=date(2026, 6, 1),
        period_end=PERIOD,
    )
    await session.flush()

    before = _lens(await score_ticker(session, "REST", date(2026, 5, 31)), "quality")
    after = _lens(await score_ticker(session, "REST", date(2026, 6, 1)), "quality")

    assert before.inputs["metrics"]["roic"]["value"] == 6.0
    assert after.inputs["metrics"]["roic"]["value"] == 24.0
    assert after.score > before.score
    # The original figure is not edited away — it still governs earlier dates.
    again = _lens(await score_ticker(session, "REST", date(2026, 5, 31)), "quality")
    assert again.inputs["metrics"]["roic"]["value"] == 6.0


async def test_sparse_company_gets_null_score_not_a_confident_one(session):
    await fixtures.add_company(
        session, "THIN", "industrials", {"pe_ratio": 12.0, "fcf_yield": 5.0}
    )
    await session.flush()

    result = _lens(await score_ticker(session, "THIN", date(2026, 6, 30)), "value")
    assert result.coverage == pytest.approx(0.4)
    assert result.score is None


async def test_negative_ebitda_reduces_coverage_through_the_full_pipeline(session):
    await fixtures.add_company(
        session, "LOSS", "industrials", dict(fixtures.BASELINE, ebitda=-25.0)
    )
    await session.flush()

    result = _lens(await score_ticker(session, "LOSS", date(2026, 6, 30)), "value")
    assert result.inputs["metrics"]["ev_ebitda"]["excluded"] == "ebitda_non_positive"
    assert result.coverage == pytest.approx(0.8)


async def test_cycle_inapplicable_for_non_cyclical_sector(session):
    await fixtures.add_company(session, "SOAP", "consumer_staples")
    await fixtures.add_company(session, "CHIP", "semiconductors")
    await session.flush()

    soap = _lens(await score_ticker(session, "SOAP", date(2026, 6, 30)), "cycle")
    chip = _lens(await score_ticker(session, "CHIP", date(2026, 6, 30)), "cycle")

    assert soap.applicable is False and soap.score is None
    assert chip.applicable is True and chip.score is not None


async def test_dispersion_null_when_fewer_than_three_lenses_usable(session):
    # Only value and quality have enough inputs; trend, growth, momentum and
    # cycle are starved, so there is no honest disagreement figure.
    from app.lenses.base import dispersion

    await fixtures.add_company(
        session,
        "SPARSE",
        "consumer_staples",
        {
            "pe_ratio": 12.0,
            "ev_ebitda": 8.0,
            "fcf_yield": 5.0,
            "price_to_book": 1.8,
            "dividend_yield": 3.0,
            "roic": 15.0,
            "gross_margin": 45.0,
            "net_debt_to_ebitda": 1.0,
            "interest_cover": 10.0,
            "fcf_conversion": 90.0,
            "ebitda": 400.0,
            "fcf": 150.0,
        },
    )
    await session.flush()

    scores = await score_ticker(session, "SPARSE", date(2026, 6, 30))
    usable = [s for s in scores if s.applicable and s.score is not None]
    assert len(usable) == 2
    assert dispersion(scores) is None


async def test_peer_percentile_used_once_the_sector_is_large_enough(session):
    await fixtures.add_sector(session, "industrials", 8, prefix="IND")
    await session.flush()

    result = _lens(await score_ticker(session, "IND00", date(2026, 6, 30)), "value")
    pe = result.inputs["metrics"]["pe_ratio"]
    assert pe["method"] == "peer_percentile"
    assert pe["peer_count"] == 8
    # IND00 holds the lowest P/E of the eight, so it is the cheapest peer.
    assert pe["score"] == pytest.approx(93.75)


async def test_small_sector_falls_back_to_absolute_bands(session):
    await fixtures.add_sector(session, "utilities", 7, prefix="UTL")
    await session.flush()

    result = _lens(await score_ticker(session, "UTL00", date(2026, 6, 30)), "value")
    assert result.inputs["metrics"]["pe_ratio"]["method"] == "absolute_bands"
    assert result.inputs["metrics"]["pe_ratio"]["peer_count"] == 7


async def test_score_universe_persists_and_is_rerunnable(session):
    await fixtures.add_company(session, "AAA", "industrials")
    await fixtures.add_company(session, "BBB", "semiconductors")
    await session.flush()
    as_of = date(2026, 6, 30)

    written = await score_universe(session, as_of)
    await session.commit()
    assert written == 12  # two tickers x six lenses

    stored = await stored_scores(session, "AAA", as_of)
    assert len(stored) == 6
    assert all(s.scoring_version == SCORING_VERSION for s in stored)
    assert _lens(stored, "cycle").applicable is False

    # Re-running the nightly job for the same date overwrites in place.
    again = await score_universe(session, as_of)
    await session.commit()
    assert again == 12
    assert len(await stored_scores(session, "AAA", as_of)) == 6
