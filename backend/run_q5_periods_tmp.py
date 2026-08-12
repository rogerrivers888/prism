"""Is the Q5 result a strategy or a crisis?

Volatility clusters. If the entire excess comes from 2020, this is one event
wearing a strategy's clothes, and the period breakdown is what says so.
"""
import asyncio, statistics
from datetime import date
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.config import settings
from app.backtest import Costs, run_pre_earnings
from app.backtest_segments import (
    matched_pool, paired_bootstrap, price_series, quintile_edges,
    realised_vol, report_dates_by_ticker,
)

PERIODS = [("2010-2013", 2010, 2013), ("2014-2017", 2014, 2017),
           ("2018-2019", 2018, 2019), ("2020-2021", 2020, 2021),
           ("2022-2023", 2022, 2023), ("2024-2026", 2024, 2026)]

async def main():
    costs = Costs(spread_bps=10.0, commission_bps=5.0)
    engine = create_async_engine(settings.async_database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        pooled = await run_pre_earnings(s, 10, 2, date(2010,1,1), date(2026,8,1), costs)
        trades = pooled["_trades"]
        holding = max(1, round(statistics.fmean([t.holding_days for t in trades])))
        names = sorted({t.ticker for t in trades})
        series = await price_series(s, names, date(2010,1,1), date(2026,8,1))
        reports = await report_dates_by_ticker(s, names)
    await engine.dispose()

    for t in trades:
        t.vol = realised_vol(series.get(t.ticker, []), t.entry_date)
    edges = quintile_edges([t.vol for t in trades if t.vol is not None])
    floor = edges[3]
    q5 = [t for t in trades if t.vol is not None and t.vol >= floor]
    pool = matched_pool(series, holding, costs, floor, reports)

    print(f"Q5, vol-matched non-earnings control, by period\n")
    print(f"{'period':<12}{'n':>7}{'mean%':>9}{'excess%':>9}{'90% band':>20}{'p':>9}")
    excesses = []
    for label, lo, hi in PERIODS:
        window = [t for t in q5 if lo <= t.entry_date.year <= hi]
        if len(window) < 30:
            print(f"{label:<12}{len(window):>7}  too few trades")
            continue
        pairs = [(t.net_return_pct, t.ticker) for t in window]
        boot = paired_bootstrap(pairs, pool, iterations=1000)
        if boot is None:
            print(f"{label:<12}{len(window):>7}  no matched control")
            continue
        mean, p5, p95, p = boot
        excesses.append(mean)
        print(f"{label:<12}{len(window):>7}{statistics.fmean([r for r,_ in pairs]):>+9.3f}"
              f"{mean:>+9.3f}{f'[{p5:+.3f},{p95:+.3f}]':>20}{p:>9.4f}")
    print(f"\nperiods positive: {sum(1 for e in excesses if e>0)} of {len(excesses)}")
    print(f"mean across periods: {statistics.fmean(excesses):+.3f}%")

asyncio.run(main())
