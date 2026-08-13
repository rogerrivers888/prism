import asyncio, time
from datetime import date
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.config import settings
from app.lenses.engine import score_universe

DATES = [date(y, m, 1) for y in range(2010, 2027) for m in (1, 4, 7, 10)
         if date(y, m, 1) <= date(2026, 7, 1)]

async def main():
    engine = create_async_engine(settings.async_database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    started = time.time()
    for index, as_of in enumerate(DATES, 1):
        async with maker() as session:
            rows = await score_universe(session, as_of)
            await session.commit()
        print(f"{index}/{len(DATES)} {as_of} {rows} rows [{time.time()-started:.0f}s]", flush=True)
    await engine.dispose()

asyncio.run(main())
