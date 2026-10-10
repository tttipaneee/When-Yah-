from datetime import datetime, timedelta
from functools import lru_cache

from fastapi import APIRouter

from api.forecast import forecast
from api.schemas import ForecastRequest, ForecastResponse

router = APIRouter()


@router.post("/api/forecast", response_model=ForecastResponse)
def post_forecast(req: ForecastRequest) -> ForecastResponse:
    return forecast(req)


@router.post("/api/explain")
def post_explain(req: ForecastRequest) -> dict:
    """Plain-language explanation by Claude from this forecast's facts only (api/explain.py); ai=false on any failure."""
    from api.explain import explain
    return explain(req)


@lru_cache(maxsize=512)
def _route_now(a: tuple[float, float], b: tuple[float, float], depart_iso: str | None, minute: str) -> dict:
    from api.traffic import route_with_traffic
    r = route_with_traffic(a, b, datetime.fromisoformat(depart_iso) if depart_iso else None)
    if not r:
        return {"km": None, "minutes": None, "source": None}
    return {"km": round(r[0], 1), "minutes": round(r[1], 1), "source": "TomTom traffic prediction"}


@router.get("/api/route")
def get_route(from_lat: float, from_lon: float, to_lat: float, to_lon: float, at: datetime | None = None) -> dict:
    """Trip time with traffic for leaving now (or at a future `at`, e.g. the presenter time), so the map can show
    it before any forecast. One TomTom call, cached per minute; nulls without TOMTOM_API_KEY or on error.
    Minutes only: traffic is not a price-model input (reports/traffic_experiment.md)."""
    now = datetime.now(at.tzinfo) if at and at.tzinfo else None
    depart = at.replace(second=0, microsecond=0).isoformat() if at and now and at > now + timedelta(minutes=2) else None
    a, b = (round(from_lat, 5), round(from_lon, 5)), (round(to_lat, 5), round(to_lon, 5))
    return _route_now(a, b, depart, datetime.utcnow().strftime("%Y-%m-%dT%H:%M"))


@lru_cache(maxsize=512)
def _usual(a: tuple[float, float], b: tuple[float, float], at_iso: str) -> dict | None:
    from api.fare import estimate
    return estimate(a, b, datetime.fromisoformat(at_iso))


@router.get("/api/usual")
def get_usual(from_lat: float, from_lon: float, to_lat: float, to_lon: float, at: datetime | None = None) -> dict:
    """Estimated usual price for the route, shown before any forecast:
    formula = Grab published rates (Jan 2023) x route km/minutes (api/fare.py), rough unless reports/fare_check.json
    passed; trained = model v2's usual price for this hour/weekend vs a place's usual (NYC ride data,
    reports/metrics_v2.md), as a factor. The forecast uses the formula value only (never the factor)."""
    from zoneinfo import ZoneInfo
    from api.forecast import load_v2
    kl = ZoneInfo("Asia/Kuala_Lumpur")
    t = (at.astimezone(kl) if at and at.tzinfo else at.replace(tzinfo=kl)) if at else datetime.now(kl)
    a, b = (round(from_lat, 5), round(from_lon, 5)), (round(to_lat, 5), round(to_lon, 5))
    est = _usual(a, b, t.replace(second=0, microsecond=0).isoformat())
    if not est:
        return {"rm": None}
    out = dict(est)
    v2 = load_v2()
    if v2 is not None:
        f = float(v2["normal_table"].get((int(t.weekday() >= 5), t.hour), 1.0))
        out.update(time_factor=round(f, 3), rm_at_this_time=round(est["rm"] * f, 2),
                   time_source="usual price by hour and weekday vs a place's usual, NYC ride data Aug 2024 "
                               "(reports/metrics_v2.md)")
    return out
