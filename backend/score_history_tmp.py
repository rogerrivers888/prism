"""Score the universe quarterly across the backtest window.

Segmenting on lens readings needs those readings as they stood at entry. Using
today's scores to classify a 2012 trade would be the exact lookahead the
harness exists to prevent, so the scores are recomputed at historical dates
from point-in-time fundamentals instead.
"""
import asyncio, time
from datetime import date
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.config import settings
from app.lenses.engine import score_universe

DATES = [
    date(year, month, 1)
    for year in range(2010, 2027)
    for month in (1, 4, 7, 10)
    if date(year, month, 1) <= date(2026, 7, 1)
]

async def main():
    engine = create_async_engine(settings.async_database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    started = time.time()
    for index, as_of in enumerate(DATES, 1):
        async with maker() as session:
            rows = await score_universe(session, as_of)
            await session.commit()
        print(f"{index}/{len(DATES)} {as_of} {rows} rows  [{time.time()-started:.0f}s]", flush=True)
    await engine.dispose()

asyncio.run(main())
