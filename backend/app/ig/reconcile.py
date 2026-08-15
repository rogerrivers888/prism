"""Reconciling IG's view of the book against Prism's.

Three outcomes, and none of them is applied automatically:

  matched     — an IG position and a Prism position that look like the same
                trade. Linked, never merged: Prism's record of Roger's
                reasoning stays intact and IG's record of the fill stays
                intact, and the link says they refer to one thing.
  ig_only     — IG knows about a position Prism does not. Created with a
                prominent "add your thesis" flag, because the whole point of
                the Decisions discipline is that it happens.
  prism_only  — Prism has a position IG does not report. Flagged as "not
                found at IG — closed, or a manual entry?" and left alone.

Nothing is silently merged and nothing is deleted. A wrong automatic merge
would attach one trade's reasoning to another's fills, and there is no way to
notice afterwards.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ig.models import IGEpicMap, IGPosition, IGReconciliation
from app.projections.positions import Position

logger = logging.getLogger(__name__)

# How close two sizes must be to count as the same trade.
SIZE_TOLERANCE = 0.05
# And how far apart their opening dates may sit, in days.
DATE_TOLERANCE_DAYS = 5


@dataclass
class Candidate:
    kind: str
    confidence: float
    reason: str
    ig: IGPosition | None = None
    prism: Position | None = None
    detail: dict = field(default_factory=dict)


def _same_direction(ig_direction: str, prism_direction: str) -> bool:
    return (
        (ig_direction.upper() == "BUY" and prism_direction.lower() in ("long", "buy"))
        or (ig_direction.upper() == "SELL" and prism_direction.lower() in ("short", "sell"))
    )


def score_match(ig: IGPosition, prism: Position, ticker: str | None) -> tuple[float, str]:
    """How confident are we that these are the same trade?

    Instrument and direction are required — without both, this is not a match
    at any confidence. Size and date raise the score but cannot substitute.
    """
    if not ticker or prism.ticker.upper() != ticker.upper():
        return 0.0, "different instrument"
    if not _same_direction(ig.direction, prism.direction):
        return 0.0, "opposite direction"

    confidence = 0.6
    reasons = ["same instrument and direction"]

    ig_size = abs(float(ig.size))
    prism_size = abs(float(prism.size))
    if prism_size > 0 and ig_size > 0:
        ratio = min(ig_size, prism_size) / max(ig_size, prism_size)
        if ratio >= 1 - SIZE_TOLERANCE:
            confidence += 0.25
            reasons.append(f"sizes agree ({ig_size:g} vs {prism_size:g})")
        else:
            reasons.append(f"sizes differ ({ig_size:g} vs {prism_size:g})")

    if ig.opened_at and prism.opened_at:
        gap = abs((ig.opened_at.date() - prism.opened_at.date()).days)
        if gap <= DATE_TOLERANCE_DAYS:
            confidence += 0.15
            reasons.append(f"opened within {gap} day(s)")
        else:
            reasons.append(f"opened {gap} days apart")

    return min(confidence, 1.0), "; ".join(reasons)


async def build(session: AsyncSession, account_id: str | None = None) -> list[Candidate]:
    """Work out what matches what. Writes nothing."""
    ig_query = select(IGPosition).where(IGPosition.closed_at.is_(None))
    if account_id:
        ig_query = ig_query.where(IGPosition.account_id == account_id)
    ig_positions = list((await session.execute(ig_query)).scalars())

    prism_positions = list(
        (await session.execute(select(Position).where(Position.status == "open"))).scalars()
    )
    epics = {
        row.epic: row
        for row in (await session.execute(select(IGEpicMap))).scalars()
    }

    candidates: list[Candidate] = []
    claimed_prism: set = set()

    for ig in ig_positions:
        epic = epics.get(ig.epic)
        ticker = (epic.ticker or epic.underlying_ticker) if epic else None

        best: tuple[float, str, Position] | None = None
        for prism in prism_positions:
            if prism.stream_id in claimed_prism:
                continue
            confidence, reason = score_match(ig, prism, ticker)
            if confidence > 0 and (best is None or confidence > best[0]):
                best = (confidence, reason, prism)

        if best and best[0] >= 0.6:
            claimed_prism.add(best[2].stream_id)
            candidates.append(Candidate(
                kind="matched", confidence=best[0], reason=best[1],
                ig=ig, prism=best[2],
                detail={
                    "epic": ig.epic, "ticker": ticker,
                    "ig_size": str(ig.size), "prism_size": str(best[2].size),
                    "ig_direction": ig.direction, "prism_direction": best[2].direction,
                    "instrument_kind": epic.kind if epic else "unknown",
                },
            ))
        else:
            candidates.append(Candidate(
                kind="ig_only", confidence=1.0,
                reason=(
                    "IG reports this position and Prism has no record of it. "
                    "Import it and add your thesis."
                ),
                ig=ig,
                detail={
                    "epic": ig.epic, "ticker": ticker,
                    "instrument_name": epic.instrument_name if epic else None,
                    "instrument_kind": epic.kind if epic else "unknown",
                    "size": str(ig.size), "direction": ig.direction,
                    "currency": ig.currency,
                    "needs_mapping": bool(epic and epic.needs_review),
                },
            ))

    for prism in prism_positions:
        if prism.stream_id in claimed_prism:
            continue
        candidates.append(Candidate(
            kind="prism_only", confidence=1.0,
            reason=(
                "Prism has this position open but IG does not report it. "
                "Closed at IG, or recorded here by hand?"
            ),
            prism=prism,
            detail={
                "ticker": prism.ticker, "size": str(prism.size),
                "direction": prism.direction,
                "instrument_type": prism.instrument_type,
                "opened_at": prism.opened_at.isoformat() if prism.opened_at else None,
            },
        ))

    return candidates


async def stage(session: AsyncSession, candidates: list[Candidate]) -> int:
    """Record the proposals as pending. Applies nothing.

    Deliberately a separate step from build(): the first sync produces a
    review screen, and only an explicit decision by Roger turns a proposal
    into a link or an imported position.
    """
    written = 0
    for candidate in candidates:
        existing = (
            await session.execute(
                select(IGReconciliation).where(
                    IGReconciliation.kind == candidate.kind,
                    IGReconciliation.deal_id == (candidate.ig.deal_id if candidate.ig else None),
                    IGReconciliation.prism_stream_id == (
                        candidate.prism.stream_id if candidate.prism else None
                    ),
                    IGReconciliation.status == "pending",
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue
        session.add(IGReconciliation(
            account_id=candidate.ig.account_id if candidate.ig else "prism",
            kind=candidate.kind,
            deal_id=candidate.ig.deal_id if candidate.ig else None,
            epic=candidate.ig.epic if candidate.ig else None,
            ticker=candidate.detail.get("ticker"),
            prism_stream_id=candidate.prism.stream_id if candidate.prism else None,
            detail={**candidate.detail, "reason": candidate.reason},
            confidence=candidate.confidence,
            status="pending",
        ))
        written += 1
    await session.flush()
    return written


def summarise(candidates: list[Candidate]) -> dict:
    counts: dict[str, int] = {}
    for candidate in candidates:
        counts[candidate.kind] = counts.get(candidate.kind, 0) + 1
    return {
        "total": len(candidates),
        "matched": counts.get("matched", 0),
        "ig_only": counts.get("ig_only", 0),
        "prism_only": counts.get("prism_only", 0),
        "needs_mapping": sum(
            1 for c in candidates if c.detail.get("needs_mapping")
        ),
    }
