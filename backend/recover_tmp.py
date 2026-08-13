"""Recover departed constituents: prices + fundamentals for every membership
ticker we do not hold. Reports the recovery rate — the number that says how
much of the survivorship problem is actually repairable."""
import asyncio, json, logging, os
from datetime import date, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.config import settings
from app.fundamentals import PriceDaily, Security
from app.ingest.budget import CallBudget
from app.ingest.eodhd import EODHDProvider
from app.ingest.constituents import IndexMembership
from app.ingest.runner import sync_universe

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)

async def main():
    engine = create_async_engine(settings.async_database_url)
    provider = EODHDProvider(api_key=os.environ["EODHD_API_KEY"])
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        membership = list((await s.execute(select(IndexMembership))).scalars())
        held = set((await s.execute(select(Security.ticker))).scalars())
        missing = sorted({m.ticker for m in membership} - held)
        print(f"membership tickers: {len({m.ticker for m in membership})}, "
              f"already held: {len({m.ticker for m in membership} & held)}, "
              f"to recover: {len(missing)}")

        budget = CallBudget(s, provider.name, limit=100_000)
        report = await sync_universe(
            s, provider, budget, [f"{t}.US" for t in missing], with_dividends=True,
        )
        await s.commit()
        print("ingested:", report.ingested, "failed:", len(report.failed))
        print("unmapped sectors:", dict(report.unmapped_sectors))

        # Departed-and-dead companies must not appear in live screens; the
        # engine reaches them through membership, not through is_active.
        recovered = set((await s.execute(select(Security.ticker))).scalars()) - held
        stale_cutoff = date.today() - timedelta(days=30)
        deactivated = 0
        for ticker in recovered:
            last = (await s.execute(
                select(PriceDaily.date).where(PriceDaily.ticker == ticker)
                .order_by(PriceDaily.date.desc()).limit(1)
            )).scalar()
            if last is None or last < stale_cutoff:
                security = await s.get(Security, ticker)
                security.is_active = False
                deactivated += 1
        await s.commit()
        print(f"recovered {len(recovered)}; {deactivated} marked inactive (delisted/stale), "
              f"{len(recovered) - deactivated} still trade and stay active")

        failures = {k: v for k, v in report.failed.items() if not k.startswith("_")}
        json.dump({"missing": missing, "failed": failures,
                   "recovered": sorted(recovered)}, open("/tmp/recovery.json", "w"))
    await engine.dispose()

asyncio.run(main())
