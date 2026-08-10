from fastapi import FastAPI

from app.events.router import router as dev_events_router

app = FastAPI(title="Prism API")

# DEV-ONLY: temporary event-store endpoints, remove once real ones exist.
app.include_router(dev_events_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "prism-api"}
