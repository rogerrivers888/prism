"""Register the first generation and run each through the gate.

Idempotent: a strategy already registered under the same rule signature is
skipped rather than duplicated. Nothing is promoted — the results are recorded
for Roger to approve strategy by strategy.
"""

import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.strategies import registry
from app.strategies.catalogue import entries
from app.strategies.features import FeatureService
from app.strategies.gate import run_gate
from app.strategies.rules import features_used, parse_rules, rule_signature

logger = logging.getLogger(__name__)


async def register_catalogue(session: AsyncSession) -> dict:
    registered, skipped = [], []
    for card in entries():
        signature = rule_signature(card["rules"])
        existing = (
            await session.execute(
                select(registry.Strategy).where(registry.Strategy.rule_signature == signature)
            )
        ).scalar_one_or_none()
        if existing is not None:
            skipped.append(existing.name)
            continue
        strategy_id = await registry.register(
            session,
            name=card["name"],
            hypothesis=card["hypothesis"],
            authority=card["authority"],
            citation=card["citation"],
            rules=card["rules"],
            horizon=card["horizon"],
            expected_trade_frequency=card["expected_trade_frequency"],
            expected_holding_period=card["expected_holding_period"],
            predicted_performance=card["predicted_performance"],
            encoding_deviations=card["encoding_deviations"],
            decay_note=card["decay_note"],
        )
        registered.append((card["name"], strategy_id))
    await session.commit()
    return {"registered": registered, "skipped": skipped}


async def gate_all(session: AsyncSession, start: date, end: date) -> list[dict]:
    """Backtest every registered strategy that has no result yet.

    One FeatureService is built for the union of every strategy's features and
    shared across all of them — the data load dominates, and twelve separate
    loads of the same universe would be twelve times the wait for nothing.
    """
    strategies = list((await session.execute(select(registry.Strategy))).scalars())
    needed: set[str] = set()
    for strategy in strategies:
        rules = parse_rules(strategy.rules)
        needed |= features_used(rules)
        if rules.universe.min_market_cap or rules.universe.max_market_cap:
            needed.add("price:market_cap")

    logger.info("building features for %d strategies, %d distinct features",
                len(strategies), len(needed))
    service = await FeatureService.build(
        session, start, end, needed, membership_index="GSPC.INDX"
    )
    if service.membership:
        logger.info("universe corrected: %d tickers carry membership spells",
                    len(service.membership))

    out = []
    for strategy in strategies:
        logger.info("gating %s", strategy.name)
        results = await run_gate(session, strategy.strategy_id, start, end, service=service)
        await session.commit()
        # Correlate against every sibling that already has a backtest.
        await registry.check_novelty(
            session, strategy.strategy_id,
            (await session.execute(
                select(registry.StrategyBacktest.monthly_returns)
                .where(registry.StrategyBacktest.strategy_id == strategy.strategy_id)
                .order_by(registry.StrategyBacktest.id.desc()).limit(1)
            )).scalar() or [],
        )
        await session.commit()
        out.append(results)
    return out
