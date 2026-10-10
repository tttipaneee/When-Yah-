"""Presenter scenarios (PRD FR8). Every scenario runs the real forecast; the typed prices are EXAMPLES
(labelled "contoh"), not observed fares. Event pickups are real venue coordinates (OpenStreetMap)."""
from fastapi import APIRouter

from api.forecast import forecast
from api.schemas import ForecastRequest

router = APIRouter()

SCENARIOS = [
    {"id": "jam", "title": "Sesak, Jumaat 18:10 — harga 2x biasa",
     "request": {"datetime": "2026-10-16T18:10:00+08:00", "rain": False, "pickup": None,
                 "quotes": [{"app": "grab", "price_rm": 40.0}, {"app": "indrive", "price_rm": 35.0}],
                 "usual_price_rm": 20.0}},
    {"id": "mamamoo", "title": "Sabtu 19:30 dekat Unifi Arena (MAMAMOO)",
     "request": {"datetime": "2026-10-10T19:30:00+08:00", "rain": False,
                 "pickup": {"lat": 3.0537311, "lon": 101.6934618},
                 "quotes": [{"app": "grab", "price_rm": 32.0}, {"app": "indrive", "price_rm": 28.0}],
                 "usual_price_rm": 22.0}},
    {"id": "eunji_rain", "title": "Ahad 23:05 lepas konsert di Zepp KL, hujan",
     "request": {"datetime": "2026-10-11T23:05:00+08:00", "rain": True,
                 "pickup": {"lat": 3.1394413, "lon": 101.7091281},
                 "quotes": [{"app": "grab", "price_rm": 26.0}], "usual_price_rm": 16.0}},
    {"id": "quiet", "title": "Selasa 14:00, waktu tenang",
     "request": {"datetime": "2026-10-13T14:00:00+08:00", "rain": False, "pickup": None,
                 "quotes": [{"app": "grab", "price_rm": 15.0}, {"app": "gvride", "price_rm": 14.0}],
                 "usual_price_rm": 15.0}},
]


@router.get("/api/demo")
def get_demo() -> list[dict]:
    return [{**s, "label": "contoh (example prices, not real quotes)",
             "response": forecast(ForecastRequest(**s["request"])).model_dump(mode="json")} for s in SCENARIOS]
