"""When Yah? API. Run: uvicorn api.main:app --reload --port 8000"""
import os

from pathlib import Path

from fastapi import FastAPI

# load .env (e.g. TOMTOM_API_KEY) when started without scripts/run_demo.sh; never printed
_env = Path(__file__).resolve().parent.parent / ".env"
if _env.exists():
    for _line in _env.read_text(encoding="utf-8").splitlines():
        if "=" in _line and not _line.lstrip().startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))
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
