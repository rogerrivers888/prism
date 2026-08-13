import asyncio, json, logging
from datetime import date
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.config import settings
from app.strategies.registry import StrategyBacktest
from app.strategies.bootstrap_catalogue import gate_all

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logging.getLogger("sqlalchemy").setLevel(logging.WARNING)

async def main():
    engine = create_async_engine(settings.async_database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        await s.execute(delete(StrategyBacktest))
        await s.commit()
        results = await gate_all(s, date(2011, 1, 1), date(2026, 8, 1))
    json.dump(results, open("/tmp/gate_results.json", "w"), default=str)
    await engine.dispose()
asyncio.run(main())
