"""Re-run the parameter sweep inside the most promising segment.

Sign-flipping between adjacent settings was the strongest evidence against the
pooled result. If a segment carries a real effect, its excess should vary
smoothly as the entry and exit days move. If it flips sign there too, the
segment is the same noise at a smaller sample size.
"""
import asyncio, json, sys
from datetime import date
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.config import settings
from app.backtest import Costs
from app.backtest_segments import run_segmented

COMBOS = [(5, 1), (5, 3), (10, 1), (10, 2), (10, 3), (15, 2), (20, 1), (20, 3)]

async def main():
    prior = json.load(open("/tmp/segments.json"))
    target = sys.argv[1] if len(sys.argv) > 1 else None
    if target:
        row = next(r for r in prior["segments"] if r["segment"] == target)
    else:
        row = prior["best_positive_segment"]
        if row is None:
            print("no positive segment to sweep — every segment was null or negative")
            return
    family, segment = row["family"], row["segment"]
    print(f"sweeping within {family} / {segment}")
    print(f"  base: n={row['trades']} excess {row['excess_pct']:+.3f}% "
          f"[{row['p5']:+.3f},{row['p95']:+.3f}] p={row['p_value']}\n")

    engine = create_async_engine(settings.async_database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    print(f"{'enter':>5}{'exit':>6}{'n':>8}{'mean%':>9}{'drift%':>9}{'excess%':>9}{'90% band':>20}{'p':>9}")
    out = []
    for enter, ex in COMBOS:
        async with maker() as s:
            r = await run_segmented(s, enter, ex, date(2010,1,1), date(2026,8,1),
                                    Costs(spread_bps=10.0, commission_bps=5.0),
                                    families_only={family})
        match = next((x for x in r["segments"] if x["segment"] == segment), None)
        if match is None:
            print(f"{enter:>5}{ex:>6}{'—':>8}  (segment empty at this setting)")
            continue
        band = f"[{match['p5']:+.3f},{match['p95']:+.3f}]"
        print(f"{enter:>5}{ex:>6}{match['trades']:>8}{match['mean_return_pct']:>+9.3f}"
              f"{match['drift_pct']:>+9.3f}{match['excess_pct']:>+9.3f}{band:>20}{match['p_value']:>9.4f}", flush=True)
        out.append({"enter": enter, "exit": ex, **match})
    await engine.dispose()

    json.dump(out, open("/tmp/segment_sweep.json","w"), default=str)
    signs = [1 if o["excess_pct"] > 0 else -1 for o in out]
    flips = sum(1 for a, b in zip(signs, signs[1:]) if a != b)
    import statistics
    print(f"\nsign flips between adjacent settings: {flips} of {len(signs)-1} transitions")
    print(f"negative settings: {sum(1 for s in signs if s < 0)} of {len(signs)}")
    print(f"mean excess across settings: {statistics.fmean([o['excess_pct'] for o in out]):+.4f}%")

asyncio.run(main())
