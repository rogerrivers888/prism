from fastapi import FastAPI

app = FastAPI(title="Prism API")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "prism-api"}
