"""When Yah? API. Run: uvicorn api.main:app --reload --port 8000"""
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import events, forecast, metrics

app = FastAPI(title="When Yah? API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("CORS_ORIGIN", "http://localhost:5173")],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.include_router(forecast.router)
app.include_router(events.router)
app.include_router(metrics.router)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}
