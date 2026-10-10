from pathlib import Path

from fastapi import APIRouter

router = APIRouter()
REPORTS = Path(__file__).resolve().parents[2] / "reports"


def _read(name: str) -> str | None:
    p = REPORTS / name
    return p.read_text(encoding="utf-8") if p.exists() else None


@router.get("/api/metrics")
def get_metrics() -> dict:
    return {"metrics": _read("metrics.md"), "event_effect": _read("event_effect.md")}
