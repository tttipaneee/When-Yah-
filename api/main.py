"""When Yah? API. Run: uvicorn api.main:app --reload --port 8000"""
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.forecast import load_bundle
from api.routes import demo, events, forecast, metrics

app = FastAPI(title="When Yah? API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("CORS_ORIGIN", "http://localhost:3000")],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.include_router(forecast.router)
app.include_router(events.router)
app.include_router(metrics.router)
app.include_router(demo.router)


load_bundle()  # load the model once at startup so the first forecast is fast


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}
