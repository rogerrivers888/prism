"""The test that decides whether the volatility result is an earnings effect.

Q5 was selected ON high trailing volatility. High trailing volatility usually
follows a drawdown, so an unmatched control credits the segment for mean
reversion that has nothing to do with earnings. This re-runs the same trades
against a control drawn from the same names at equally volatile times, away
from any report.
"""
import asyncio, json, statistics
from datetime import date
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.config import settings
from app.backtest import Costs, run_pre_earnings
from app.backtest_segments import (
    build_pool, matched_pool, paired_bootstrap, price_series,
    quintile_edges, realised_vol, report_dates_by_ticker,
)

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

    for t in trades:
        t.vol = realised_vol(series.get(t.ticker, []), t.entry_date)
    vols = [t.vol for t in trades if t.vol is not None]
    edges = quintile_edges(vols)
    floor = edges[3]
    q5 = [t for t in trades if t.vol is not None and t.vol >= floor]
    print(f"Q5 vol floor: {floor:.1f}% annualised | {len(q5)} trades | holding {holding}d\n")

    unmatched = build_pool(series, holding, costs)
    print("building volatility-matched control (same names, same vol state, away from earnings)...", flush=True)
    matched = matched_pool(series, holding, costs, floor, reports)
    print(f"matched pool: {len(matched)} tickers had enough eligible windows\n")

    pairs = [(t.net_return_pct, t.ticker) for t in q5]
    strategy_mean = statistics.fmean([r for r, _ in pairs])

    out = {}
    for label, pool in (("unmatched (random times)", unmatched), ("vol-matched, non-earnings", matched)):
        covered = [p for p in pairs if p[1] in pool]
        boot = paired_bootstrap(pairs, pool, iterations=1000)
        drift = statistics.fmean([statistics.fmean(pool[t]) for _, t in covered])
        mean, p5, p95, p = boot
        print(f"{label:<30} n={len(covered):>6}  drift {drift:+.3f}%  "
              f"excess {mean:+.3f}%  [{p5:+.3f},{p95:+.3f}]  p={p:.4f}")
        out[label] = {"n": len(covered), "drift": drift, "excess": mean, "p5": p5, "p95": p95, "p": p}

    print(f"\nQ5 strategy mean: {strategy_mean:+.3f}%")
    delta = out['unmatched (random times)']['excess'] - out['vol-matched, non-earnings']['excess']
    print(f"how much of the apparent edge was volatility state, not earnings: {delta:+.3f} pp")
    json.dump(out, open("/tmp/matched.json","w"))
    await engine.dispose()

asyncio.run(main())
