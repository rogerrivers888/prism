"""Reconciliation must never silently merge or delete."""

import uuid
from datetime import datetime, timezone

import pytest

from app.ig.models import IGEpicMap, IGPosition
from app.ig.reconcile import build, score_match, stage, summarise
from app.projections.positions import Position

NOW = datetime(2026, 8, 15, tzinfo=timezone.utc)


def ig_position(**kw):
    base = dict(deal_id="D1", account_id="ACC1", epic="CS.D.MU.CASH.IP",
                direction="BUY", size=10, last_seen=NOW, last_event_id=1,
                opened_at=NOW)
    base.update(kw)
    return IGPosition(**base)


def prism_position(**kw):
    base = dict(stream_id=uuid.uuid4(), instrument_type="share", ticker="MU",
                direction="long", size=10, entry_price=100, currency="GBP",
                opened_at=NOW, status="open", last_event_id=1)
    base.update(kw)
    return Position(**base)


def test_same_instrument_direction_and_size_scores_high():
    confidence, reason = score_match(ig_position(), prism_position(), "MU")
    assert confidence >= 0.9
    assert "sizes agree" in reason


def test_a_different_instrument_never_matches_at_any_confidence():
    confidence, _ = score_match(ig_position(), prism_position(ticker="NVDA"), "MU")
    assert confidence == 0.0


def test_opposite_directions_never_match():
    """Matching a long to a short would attach the reasoning for a bet on a
    rise to a bet on a fall."""
    confidence, _ = score_match(ig_position(direction="SELL"), prism_position(), "MU")
    assert confidence == 0.0


def test_an_unmapped_epic_cannot_match_anything():
    confidence, _ = score_match(ig_position(), prism_position(), None)
    assert confidence == 0.0


def test_size_mismatch_lowers_confidence_but_can_still_match():
    close, _ = score_match(ig_position(size=10), prism_position(size=10), "MU")
    far, reason = score_match(ig_position(size=10), prism_position(size=40), "MU")
    assert far < close
    assert "sizes differ" in reason


@pytest.mark.asyncio
async def test_build_classifies_all_three_outcomes(session):
    session.add(IGEpicMap(epic="CS.D.TESTA.CASH.IP", ticker="TESTA", kind="equity",
                          needs_review=False, mapped_by="auto"))
    session.add(IGEpicMap(epic="CS.D.TESTB.CASH.IP", ticker="TESTB", kind="equity",
                          needs_review=False, mapped_by="auto"))
    session.add(ig_position(deal_id="MATCH", epic="CS.D.TESTA.CASH.IP",
                            account_id="RECON1"))
    session.add(ig_position(deal_id="IGONLY", epic="CS.D.TESTB.CASH.IP",
                            account_id="RECON1", size=7))
    matched = prism_position(ticker="TESTA", size=10)
    orphan = prism_position(ticker="TESTC", size=3)
    session.add_all([matched, orphan])
    await session.flush()

    candidates = await build(session, account_id="RECON1")
    kinds = {c.kind for c in candidates}
    assert {"matched", "ig_only", "prism_only"} <= kinds

    match = next(c for c in candidates if c.kind == "matched")
    assert match.prism.ticker == "TESTA"
    assert match.confidence >= 0.6

    ig_only = next(c for c in candidates if c.kind == "ig_only" and c.ig.deal_id == "IGONLY")
    assert "add your thesis" in ig_only.reason

    orphans = [c for c in candidates if c.kind == "prism_only"]
    assert any(c.prism.ticker == "TESTC" for c in orphans)
    assert all("Closed at IG, or recorded here by hand" in c.reason for c in orphans)


@pytest.mark.asyncio
async def test_one_prism_position_is_claimed_only_once(session):
    """Two IG positions in the same instrument must not both claim the same
    Prism record — that would double-link one trade."""
    session.add(IGEpicMap(epic="CS.D.DUPE.CASH.IP", ticker="DUPE", kind="equity",
                          needs_review=False, mapped_by="auto"))
    session.add(ig_position(deal_id="DUP1", epic="CS.D.DUPE.CASH.IP", account_id="DUPACC"))
    session.add(ig_position(deal_id="DUP2", epic="CS.D.DUPE.CASH.IP", account_id="DUPACC"))
    session.add(prism_position(ticker="DUPE"))
    await session.flush()

    candidates = await build(session, account_id="DUPACC")
    matched = [c for c in candidates if c.kind == "matched"]
    assert len(matched) == 1, "a Prism position was claimed twice"
    assert any(c.kind == "ig_only" for c in candidates)


@pytest.mark.asyncio
async def test_staging_writes_proposals_as_pending_and_is_idempotent(session):
    session.add(IGEpicMap(epic="CS.D.STG.CASH.IP", ticker="STG", kind="equity",
                          needs_review=False, mapped_by="auto"))
    session.add(ig_position(deal_id="STAGE1", epic="CS.D.STG.CASH.IP", account_id="STGACC"))
    await session.flush()

    candidates = await build(session, account_id="STGACC")
    first = await stage(session, candidates)
    second = await stage(session, candidates)
    assert first > 0
    assert second == 0, "re-staging must not duplicate pending proposals"


def test_summary_counts_each_kind():
    from app.ig.reconcile import Candidate

    counts = summarise([
        Candidate(kind="matched", confidence=1, reason=""),
        Candidate(kind="ig_only", confidence=1, reason="", detail={"needs_mapping": True}),
        Candidate(kind="prism_only", confidence=1, reason=""),
    ])
    assert counts == {"total": 3, "matched": 1, "ig_only": 1,
                      "prism_only": 1, "needs_mapping": 1}
