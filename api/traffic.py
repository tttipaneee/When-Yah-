"""Predicted trip time per departure (now, +15, +30, +45, +60 min) from TomTom Routing (traffic-aware).

TomTom's calculateRoute with `departAt` returns the travel time for that departure using live and
historical traffic: https://developer.tomtom.com/routing-api/documentation/routing/calculate-route
Needs TOMTOM_API_KEY in .env (free tier). Without a key, or on any error, returns None and the app simply
shows no traffic. Used only for traffic warnings — not as a price-model input
(reports/traffic_experiment.md: traffic did not improve price prediction).
"""
import json
import os
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from functools import lru_cache

URL = "https://api.tomtom.com/routing/1/calculateRoute/{a_lat},{a_lon}:{b_lat},{b_lon}/json"
_ENV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")


def _tomtom_key() -> str | None:
    """TOMTOM_API_KEY from the environment or the project .env (so scripts like ml.fare_check find it too)."""
    if not os.getenv("TOMTOM_API_KEY") and os.path.exists(_ENV):
        for line in open(_ENV, encoding="utf-8"):
            if line.strip().startswith("TOMTOM_API_KEY=") and "=" in line:
                os.environ["TOMTOM_API_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.getenv("TOMTOM_API_KEY") or None
DEPARTURES = (0, 15, 30, 45, 60)


def _minutes(a: tuple[float, float], b: tuple[float, float], depart: datetime, key: str) -> float | None:
    q = {"key": key, "traffic": "true", "travelMode": "car", "routeType": "fastest",
         "departAt": "now" if depart is None else depart.isoformat(timespec="seconds")}
    url = URL.format(a_lat=a[0], a_lon=a[1], b_lat=b[0], b_lon=b[1]) + "?" + urllib.parse.urlencode(q)
    try:
        with urllib.request.urlopen(url, timeout=6) as r:
            return json.load(r)["routes"][0]["summary"]["travelTimeInSeconds"] / 60
    except Exception:
        return None


@lru_cache(maxsize=256)
def _cached(a: tuple[float, float], b: tuple[float, float], start_iso: str, key: str) -> tuple:
    start = datetime.fromisoformat(start_iso)
    now = datetime.now(start.tzinfo)
    # forecast for the future (e.g. Monday 17:00): every departure is start + m; for "now" (or a past time,
    # which TomTom rejects) the first departure is "now" and the rest are counted from the current time
    future = start > now + timedelta(minutes=2)
    base = start if future else now
    deps = [base + timedelta(minutes=m) if (future or m) else None for m in DEPARTURES]
    with ThreadPoolExecutor(max_workers=5) as ex:
        mins = list(ex.map(lambda d: _minutes(a, b, d, key), deps))
    return tuple(mins)


def predicted_minutes(a: tuple[float, float], b: tuple[float, float], start: datetime) -> dict[int, float] | None:
    """{minutes_from_now: predicted trip minutes} or None (no key / no answer)."""
    key = _tomtom_key()
    if not key:
        return None
    start = start.replace(second=0, microsecond=0)  # cache per minute
    a, b = (round(a[0], 5), round(a[1], 5)), (round(b[0], 5), round(b[1], 5))
    mins = _cached(a, b, start.isoformat(), key)
    out = {m: round(v, 1) for m, v in zip(DEPARTURES, mins) if v}
    return out if 0 in out and len(out) > 1 else None


def route_with_traffic(a: tuple[float, float], b: tuple[float, float], depart: datetime | None = None,
                       timeout: float = 8) -> tuple[float, float] | None:
    """(km, traffic-aware minutes) from TomTom for one departure (None = now). None without key / on error."""
    key = _tomtom_key()
    if not key:
        return None
    q = {"key": key, "traffic": "true", "travelMode": "car", "routeType": "fastest",
         "departAt": "now" if depart is None else depart.isoformat(timespec="seconds")}
    url = URL.format(a_lat=a[0], a_lon=a[1], b_lat=b[0], b_lon=b[1]) + "?" + urllib.parse.urlencode(q)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            sm = json.load(r)["routes"][0]["summary"]
        return sm["lengthInMeters"] / 1000, sm["travelTimeInSeconds"] / 60
    except Exception:
        return None
