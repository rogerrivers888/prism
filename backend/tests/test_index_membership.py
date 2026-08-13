"""Membership-as-of: the survivorship repair, and its honesty about gaps."""

from datetime import date

import pytest

from app.ingest.constituents import (
    INCEPTION,
    IndexMembership,
    members_as_of,
    parse_membership,
    store,
)


PAYLOAD = {
    "HistoricalTickerComponents": {
        "0": {"Code": "ALIVE", "Name": "Alive Corp", "StartDate": "2010-05-01",
              "EndDate": None, "IsActiveNow": 1, "IsDelisted": 0},
        "1": {"Code": "DEAD", "Name": "Dead Corp", "StartDate": "2012-03-01",
              "EndDate": "2019-06-01", "IsActiveNow": 0, "IsDelisted": 1},
        # The Aetna shape: departure known, join unknown. These are the
        # majority of the survivorship problem and must not be dropped.
        "2": {"Code": "OLDTIMER", "Name": "Old Timer Inc", "StartDate": None,
              "EndDate": "2018-12-03", "IsActiveNow": 0, "IsDelisted": 1},
        # No dates at all and not current: unusable.
        "3": {"Code": "GHOST", "Name": "??", "StartDate": None,
              "EndDate": None, "IsActiveNow": 0, "IsDelisted": 0},
    }
}


def test_parse_keeps_departures_with_unknown_joins():
    rows = parse_membership("GSPC.INDX", PAYLOAD, "test")
    by_ticker = {r["ticker"]: r for r in rows}
    assert "GHOST" not in by_ticker
    old = by_ticker["OLDTIMER"]
    assert old["joined_on"] == INCEPTION
    assert old["joined_estimated"] is True
    assert old["left_on"] == date(2018, 12, 3)
    assert by_ticker["ALIVE"]["joined_estimated"] is False


@pytest.mark.asyncio
async def test_members_as_of_is_point_in_time(session):
    await store(session, parse_membership("TEST.INDX", PAYLOAD, "test"))

    # 2015: all three members. OLDTIMER counts despite the estimated join.
    mid = await members_as_of(session, "TEST.INDX", date(2015, 1, 1))
    assert mid == {"ALIVE", "DEAD", "OLDTIMER"}

    # 2020: the departed are gone.
    late = await members_as_of(session, "TEST.INDX", date(2020, 1, 1))
    assert late == {"ALIVE"}

    # 2011: DEAD had not joined yet.
    early = await members_as_of(session, "TEST.INDX", date(2011, 1, 1))
    assert early == {"ALIVE", "OLDTIMER"}

    # The departure day itself: left_on is exclusive — the record says the
    # spell ended that day, so the name is no longer selectable.
    boundary = await members_as_of(session, "TEST.INDX", date(2019, 6, 1))
    assert "DEAD" not in boundary


@pytest.mark.asyncio
async def test_reingest_updates_the_open_spell(session):
    await store(session, parse_membership("TEST2.INDX", {
        "HistoricalTickerComponents": {
            "0": {"Code": "X", "Name": "X", "StartDate": "2020-01-01",
                  "EndDate": None, "IsActiveNow": 1, "IsDelisted": 0},
        }
    }, "test"))
    # Next sync: X has left.
    await store(session, parse_membership("TEST2.INDX", {
        "HistoricalTickerComponents": {
            "0": {"Code": "X", "Name": "X", "StartDate": "2020-01-01",
                  "EndDate": "2026-05-01", "IsActiveNow": 0, "IsDelisted": 0},
        }
    }, "test"))
    members = await members_as_of(session, "TEST2.INDX", date(2026, 6, 1))
    assert members == set()
    row = await session.get(IndexMembership, ("TEST2.INDX", "X", date(2020, 1, 1)))
    assert row.left_on == date(2026, 5, 1)
