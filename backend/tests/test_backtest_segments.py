"""Segmenting multiplies the number of tests, and these pin the arithmetic
that keeps that honest."""

from datetime import date

from app.backtest_segments import (
    benjamini_hochberg,
    bucket,
    most_recent,
    paired_bootstrap,
    quintile_edges,
    realised_vol,
)


def test_bh_rejects_nothing_when_every_p_is_large():
    assert benjamini_hochberg([0.4, 0.6, 0.9, 0.5]) == [False] * 4


def test_bh_is_stricter_than_an_uncorrected_threshold():
    """Three p-values below 0.05 out of twenty, none surviving FDR.

    This is the exact situation segmenting creates: a handful of segments look
    significant, and the correction says they are what twenty tests produce.
    """
    p_values = [0.03, 0.04, 0.045] + [0.5] * 17
    uncorrected = [p <= 0.05 for p in p_values]
    corrected = benjamini_hochberg(p_values)
    assert sum(uncorrected) == 3
    assert sum(corrected) == 0


def test_bh_keeps_a_genuinely_strong_result():
    corrected = benjamini_hochberg([0.0001, 0.5, 0.6, 0.7])
    assert corrected[0] is True
    assert sum(corrected) == 1


def test_paired_bootstrap_reports_no_excess_when_the_pool_matches():
    """Trades drawn from the same distribution as their control must not show
    an excess. If this ever fails, every segment result is inflated."""
    returns = [(0.5 if i % 2 else -0.5, "A") for i in range(400)]
    pool = {"A": [0.5, -0.5] * 100}
    result = paired_bootstrap(returns, pool, iterations=300)
    assert result is not None
    mean, p5, p95, p_value = result
    assert p5 <= 0 <= p95
    assert p_value > 0.05


def test_paired_bootstrap_finds_a_real_gap():
    returns = [(2.0, "A")] * 400
    pool = {"A": [0.0] * 100}
    result = paired_bootstrap(returns, pool, iterations=300)
    assert result is not None
    mean, p5, p95, p_value = result
    assert mean == 2.0
    assert p5 > 0


def test_paired_bootstrap_needs_a_sample():
    assert paired_bootstrap([(1.0, "A")] * 10, {"A": [0.0]}) is None


def test_paired_bootstrap_p_value_is_floored_by_resample_count():
    """A bootstrap of 300 draws cannot evidence a p below 1/300, and must not
    report 0.0 as though it could."""
    result = paired_bootstrap([(5.0, "A")] * 100, {"A": [0.0] * 50}, iterations=300)
    assert result is not None
    assert result[3] >= 1 / 300


def test_quintiles_split_evenly():
    edges = quintile_edges(list(range(100)))
    assert [bucket(v, edges) for v in (0, 25, 45, 65, 99)] == [0, 1, 2, 3, 4]


def test_most_recent_never_looks_forward():
    dates = [date(2020, 1, 1), date(2020, 4, 1), date(2020, 7, 1)]
    assert most_recent(dates, date(2020, 5, 15)) == date(2020, 4, 1)
    assert most_recent(dates, date(2020, 4, 1)) == date(2020, 4, 1)
    # A trade before any scoring run cannot be classified, and gets nothing
    # rather than the earliest available reading.
    assert most_recent(dates, date(2019, 12, 31)) is None


def test_volatility_uses_only_bars_before_entry():
    """A spike after the entry date must not classify the trade before it."""
    import datetime

    calm = [
        (date(2020, 1, 1) + datetime.timedelta(days=i), 100.0 + (i % 2) * 0.1)
        for i in range(120)
    ]
    spiked = calm + [
        (date(2020, 1, 1) + datetime.timedelta(days=120 + i), 100.0 * (3 if i % 2 else 1))
        for i in range(40)
    ]
    entry = date(2020, 1, 1) + datetime.timedelta(days=115)
    assert realised_vol(calm, entry) == realised_vol(spiked, entry)
