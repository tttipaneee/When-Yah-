import json
import re
from pathlib import Path

from fastapi import APIRouter

router = APIRouter()
REPORTS = Path(__file__).resolve().parents[2] / "reports"
EXPERIMENTS = ["trend_experiment", "borough_experiment", "traffic_experiment", "extreme_experiment", "fare_check"]


def _read(name: str) -> str | None:
    p = REPORTS / name
    return p.read_text(encoding="utf-8") if p.exists() else None


def _json(name: str) -> dict | None:
    t = _read(name)
    return json.loads(t) if t else None


@router.get("/api/case_studies")
def get_case_studies() -> dict:
    """Study cases (event exit, surge fall-back) from reports/case_studies.json — numbers of reports/case_studies.md."""
    return _json("case_studies.json") or {}


@router.get("/api/metrics")
def get_metrics() -> dict:
    """Report texts plus structured numbers for the judges' screen; every number comes from reports/."""
    verdicts = {}
    for e in EXPERIMENTS:
        t = _read(f"{e}.md")
        if t:
            verdicts[e] = [m.strip("* ") for m in re.findall(r"^\*\*Result[^\n]*", t, flags=re.M)]
    return {"metrics": _read("metrics.md"), "event_effect": _read("event_effect.md"),
            "structured": _json("metrics.json"), "decision": _json("decision.json"),
            "event_effect_summary": _json("event_effect.json"), "experiments": verdicts,
            "fare_check": _json("fare_check.json")}
