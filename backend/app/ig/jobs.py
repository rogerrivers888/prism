"""IG sync jobs: one full pass nightly, a light positions poll intraday.

IG's rate limits are strict and per-application, so this is deliberately not
continuous. The nightly job does everything; the intraday poll fetches only
open positions, a handful of times during UK market hours, so the Book is not
a day stale without risking the application key.

Both are idempotent and safe to retry. A failure is reported rather than
swallowed — a Book that silently shows yesterday's positions as today's is
worse than one that says it could not refresh.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.ig import funding as funding_module
from app.ig import history as history_module
from app.ig import reconcile as reconcile_module
from app.ig.client import IGClient
from app.ig.models import IGAccount, IGReconciliation
from app.ig.sync import SyncReport, sync_accounts, sync_positions
from app.ingest.archive import RawResponse

logger = logging.getLogger(__name__)

# How far back to pull history on a first run. IG caps what it will serve;
# whatever comes back is what exists.
FIRST_RUN_HISTORY_DAYS = 550
# On later runs only recent activity is needed, with overlap for safety.
INCREMENTAL_HISTORY_DAYS = 14


def build_client() -> IGClient | None:
    """None when IG is not configured, so the job skips rather than crashes."""
    if not (settings.ig_api_key and settings.ig_username and settings.ig_password):
        return None
    return IGClient(
        api_key=settings.ig_api_key,
        username=settings.ig_username,
        password=settings.ig_password,
        demo=settings.ig_demo,
    )


async def polls_used_today(session: AsyncSession) -> int:
    """Count of IG calls archived today, as a rate-limit guard."""
    since = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        await session.execute(
            select(func.count()).select_from(RawResponse).where(
                RawResponse.provider == "ig", RawResponse.fetched_at >= since
            )
        )
    ).scalar() or 0


@dataclass
class IGJobReport:
    ran: bool = False
    skipped_reason: str | None = None
    sync: dict = field(default_factory=dict)
    history: dict = field(default_factory=dict)
    funding: dict = field(default_factory=dict)
    reconciliation: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "ran": self.ran,
            "skipped_reason": self.skipped_reason,
            "sync": self.sync,
            "history": self.history,
            "funding": self.funding,
            "reconciliation": self.reconciliation,
            "errors": self.errors,
        }


async def run_nightly(session: AsyncSession, run_date: date | None = None) -> IGJobReport:
    """Full pass: accounts, positions, history, funding, reconciliation."""
    report = IGJobReport()
    client = build_client()
    if client is None:
        report.skipped_reason = (
            "IG is not configured — set IG_API_KEY, IG_USERNAME and IG_PASSWORD"
        )
        return report

    run_date = run_date or datetime.now(timezone.utc).date()

    try:
        accounts = await sync_accounts(session, client)
        await session.commit()

        sync_report = SyncReport(accounts=len(accounts))
        for account in accounts:
            await sync_positions(session, client, account, sync_report)
            await session.commit()
        report.sync = sync_report.as_dict()

        # First run pulls everything IG will give; later runs only the tail.
        seen_before = (
            await session.execute(
                select(func.count()).select_from(RawResponse).where(
                    RawResponse.provider == "ig", RawResponse.endpoint == "transactions"
                )
            )
        ).scalar() or 0
        window = (
            FIRST_RUN_HISTORY_DAYS if seen_before == 0 else INCREMENTAL_HISTORY_DAYS
        )
        since = run_date - timedelta(days=window)

        history_report = history_module.HistoryReport()
        activities: list[dict] = []
        for account in accounts:
            activities += await history_module.sync_history(
                session, client, account, since, history_report
            )
            await session.commit()
        await history_module.resolve_premiums(session, history_report, activities)
        await session.commit()
        report.history = history_report.as_dict()

        funding_report = await funding_module.accrue(
            session, run_date,
            settings.ig_benchmark_rate_pct, settings.ig_funding_premium_pct,
        )
        await session.commit()
        report.funding = funding_report.as_dict()

        # Proposals only. Nothing is applied without Roger.
        candidates = await reconcile_module.build(session)
        staged = await reconcile_module.stage(session, candidates)
        await session.commit()
        report.reconciliation = {
            **reconcile_module.summarise(candidates), "newly_staged": staged
        }
        report.ran = True
    except Exception as exc:  # noqa: BLE001 - reported, never swallowed
        await session.rollback()
        # The client scrubs credentials before raising; this is safe to log.
        report.errors.append(f"{type(exc).__name__}: {exc}")
        logger.exception("ig nightly sync failed")

    return report


async def run_intraday(session: AsyncSession) -> IGJobReport:
    """Positions only, a few times a day. Cheap enough to stay well inside
    IG's limits, and it is what makes the Book current rather than stale."""
    report = IGJobReport()
    client = build_client()
    if client is None:
        report.skipped_reason = "IG is not configured"
        return report

    used = await polls_used_today(session)
    if used >= settings.ig_max_polls_per_day:
        report.skipped_reason = (
            f"already made {used} IG calls today, at the configured cap of "
            f"{settings.ig_max_polls_per_day}"
        )
        return report

    try:
        accounts = list((await session.execute(select(IGAccount))).scalars())
        if not accounts:
            # Nothing known yet; the nightly job establishes the accounts.
            accounts = await sync_accounts(session, client)
            await session.commit()

        sync_report = SyncReport(accounts=len(accounts))
        for account in accounts:
            await sync_positions(session, client, account, sync_report)
            await session.commit()
        report.sync = sync_report.as_dict()
        report.ran = True
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        report.errors.append(f"{type(exc).__name__}: {exc}")
        logger.exception("ig intraday poll failed")

    return report
