import asyncio, json, sys
from datetime import date
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.config import settings
from app.backtest import Costs
from app.backtest_segments import run_segmented

async def main():
    engine = create_async_engine(settings.async_database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        r = await run_segmented(s, 10, 2, date(2010,1,1), date(2026,8,1),
                                Costs(spread_bps=10.0, commission_bps=5.0))
    json.dump(r, open("/tmp/segments.json","w"), default=str)

    print(f"pooled: {r['pooled']['trades']} trades, excess {r['pooled']['excess_over_drift_pct']:+.3f}%")
    print(f"holding {r['holding_days']}d | control pool {r['control_pool']['tickers']} tickers")
    print(f"unclassified: {r['unclassified']}")
    c = r["correction"]
    print(f"\nSEGMENT TESTS RUN: {r['segment_tests_run']}")
    print(f"  significant uncorrected: {c['significant_uncorrected']}  (expected by chance {c['expected_false_positives_uncorrected']})")
    print(f"  significant after FDR:   {c['significant_fdr']}")
    print(f"  significant Bonferroni:  {c['significant_bonferroni']} (alpha {c['bonferroni_alpha']})")

    fam = None
    print(f"\n{'segment':<34}{'n':>7}{'mean%':>9}{'drift%':>9}{'excess%':>9}{'90% band':>20}{'p':>9}  flags")
    for row in sorted(r["segments"], key=lambda x: (x["family"], -x["excess_pct"])):
        if row["family"] != fam:
            fam = row["family"]; print(f"-- {fam}")
        flags = []
        if row["significant_uncorrected"]: flags.append("unc")
        if row["significant_fdr"]: flags.append("FDR")
        if row["significant_bonferroni"]: flags.append("BONF")
        if row["underpowered"]: flags.append(f"UNDERPOWERED n={row['trades']}")
        band = f"[{row['p5']:+.3f},{row['p95']:+.3f}]"
        print(f"  {row['segment']:<32}{row['trades']:>7}{row['mean_return_pct']:>+9.3f}{row['drift_pct']:>+9.3f}"
              f"{row['excess_pct']:>+9.3f}{band:>20}{row['p_value']:>9.4f}  {','.join(flags)}")

    print("\nNEIGHBOUR AGREEMENT (positive sectors only)")
    if not r["neighbour_agreement"]:
        print("  no sector had a positive excess")
    for name, v in sorted(r["neighbour_agreement"].items(), key=lambda kv: -kv[1]["excess_pct"]):
        print(f"  {name:<24} {v['excess_pct']:+.3f}%  neighbours {v['neighbours_agreeing']}/{v['neighbours_checked']} "
              f"mean {v['neighbour_mean_excess_pct']}  isolated={v['isolated']}")
    print(f"\nbest positive segment: {r['best_positive_segment']}")

asyncio.run(main())
