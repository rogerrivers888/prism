from fastapi import FastAPI

from app.events.router import router as dev_events_router
from app.ingest.router import router as dev_ingest_router
from app.lenses.router import router as lenses_router
from app.projections.router import dev_router as dev_projections_router
from app.projections.router import router as positions_router
from app.worker.router import router as jobs_router

app = FastAPI(title="Prism API")

app.include_router(positions_router)
app.include_router(lenses_router)
app.include_router(jobs_router)

# DEV-ONLY: temporary endpoints, remove once real ones exist.
app.include_router(dev_events_router)
app.include_router(dev_projections_router)
app.include_router(dev_ingest_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "prism-api"}
