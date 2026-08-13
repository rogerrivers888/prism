"""Re-run all twelve gates on the corrected universe and print before/after."""
import asyncio, json, logging
from datetime import date
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.config import settings
from app.strategies.bootstrap_catalogue import gate_all

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logging.getLogger("sqlalchemy").setLevel(logging.WARNING)

async def main():
    engine = create_async_engine(settings.async_database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        results = await gate_all(s, date(2011, 1, 1), date(2026, 8, 1))
    json.dump(results, open("/tmp/gate_after.json", "w"), default=str)
    await engine.dispose()

    before = {r["name"]: r for r in json.load(open("/tmp/gate_before.json"))}
    after = {r["name"]: r for r in results}
    print(f"\n{'strategy':<38}{'univ':>10}  {'mean% b/a':>16}  {'excess% b/a':>16}  {'maxDD b/a':>15}  {'gate b/a':>10}")
    for name in sorted(after, key=lambda n: -(after[n].get("excess_over_drift_pct") or -99)):
        b, a = before.get(name, {}), after[name]
        bo, ao = b.get("overall", {}), a.get("overall", {})
        fmt = lambda v, d=2: f"{v:+.{d}f}" if isinstance(v, (int, float)) else "  -"
        print(f"{name[:37]:<38}{a.get('universe','?')[:9]:>10}  "
              f"{fmt(bo.get('mean_trade_return_pct')):>7}/{fmt(ao.get('mean_trade_return_pct')):>7}  "
              f"{fmt(b.get('excess_over_drift_pct')):>7}/{fmt(a.get('excess_over_drift_pct')):>7}  "
              f"{fmt(bo.get('max_drawdown_pct'),1):>7}/{fmt(ao.get('max_drawdown_pct'),1):>6}  "
              f"{'P' if b.get('gate',{}).get('eligible_for_paper') else 'f'}/"
              f"{'P' if a.get('gate',{}).get('eligible_for_paper') else 'f'}")

asyncio.run(main())
