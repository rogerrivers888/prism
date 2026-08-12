from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.events.router import router as dev_events_router
from app.ingest.router import router as dev_ingest_router
from app.lenses.router import router as lenses_router
from app.projections.router import dev_router as dev_projections_router
from app.projections.router import router as positions_router
from app.universe_router import router as universe_router
from app.assistant_router import router as assistant_router
from app.backtest_router import router as backtest_router
from app.earnings_router import router as earnings_router
from app.company_router import router as company_router
from app.screens_router import book, decisions_router, research, screener, watchlist_router
from app.worker.router import router as jobs_router

app = FastAPI(title="Prism API")

# The frontend is served from a different origin in development and from its
# own Railway service in production. Read-only API, single user.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://localhost:\d+|https://.*\.up\.railway\.app",
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(positions_router)
app.include_router(universe_router)
app.include_router(company_router)
app.include_router(screener)
app.include_router(watchlist_router)
app.include_router(research)
app.include_router(book)
app.include_router(decisions_router)
app.include_router(assistant_router)
app.include_router(lenses_router)
app.include_router(jobs_router)
app.include_router(earnings_router)
app.include_router(backtest_router)

# DEV-ONLY: temporary endpoints, remove once real ones exist.
app.include_router(dev_events_router)
app.include_router(dev_projections_router)
app.include_router(dev_ingest_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "prism-api"}
