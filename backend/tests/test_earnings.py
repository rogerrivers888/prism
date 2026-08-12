"""Earnings dates are point-in-time: a forecast that moved must not rewrite
what we believed before it moved."""

from datetime import date

import pytest

from app import earnings as earnings_module


@pytest.mark.asyncio
async def test_view_returns_the_belief_held_on_a_past_date(session):
    """The same period, observed twice with different report dates."""
    for observed, report in [
        (date(2026, 1, 10), date(2026, 4, 20)),
        (date(2026, 4, 1), date(2026, 4, 28)),
    ]:
        await earnings_module.store(
            session,
            [
                {
                    "ticker": "TEST",
                    "period_end": date(2026, 3, 31),
                    "observed_on": observed,
                    "report_date": report,
                    "is_estimated": True,
                    "source": "test",
                }
            ],
        )

    early = await earnings_module.latest_view(session, "TEST", date(2026, 2, 1))
    late = await earnings_module.latest_view(session, "TEST", date(2026, 4, 10))

    # On 1 February we thought 20 April. Asking that question later must still
    # return 20 April, or a backtest entering on 1 February would be acting on
    # a date published two months after it acted.
    assert [r.report_date for r in early] == [date(2026, 4, 20)]
    assert [r.report_date for r in late] == [date(2026, 4, 28)]


@pytest.mark.asyncio
async def test_next_report_ignores_dates_already_passed(session):
    await earnings_module.store(
        session,
        [
            {
                "ticker": "TEST2",
                "period_end": date(2025, 12, 31),
                "observed_on": date(2026, 1, 1),
                "report_date": date(2026, 1, 15),
                "is_estimated": False,
                "source": "test",
            },
            {
                "ticker": "TEST2",
                "period_end": date(2026, 3, 31),
                "observed_on": date(2026, 1, 1),
                "report_date": date(2026, 4, 20),
                "is_estimated": True,
                "source": "test",
            },
        ],
    )
    upcoming = await earnings_module.next_report(session, "TEST2", date(2026, 2, 1))
    assert upcoming is not None
    assert upcoming.report_date == date(2026, 4, 20)
