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
    deps = [None if m == 0 else start + timedelta(minutes=m) for m in DEPARTURES]
    with ThreadPoolExecutor(max_workers=5) as ex:
        mins = list(ex.map(lambda d: _minutes(a, b, d, key), deps))
    return tuple(mins)


def predicted_minutes(a: tuple[float, float], b: tuple[float, float], start: datetime) -> dict[int, float] | None:
    """{minutes_from_now: predicted trip minutes} or None (no key / no answer)."""
    key = os.getenv("TOMTOM_API_KEY")
    if not key:
        return None
    start = start.replace(second=0, microsecond=0)  # cache per minute
    a, b = (round(a[0], 5), round(a[1], 5)), (round(b[0], 5), round(b[1], 5))
    mins = _cached(a, b, start.isoformat(), key)
    out = {m: round(v, 1) for m, v in zip(DEPARTURES, mins) if v}
    return out if 0 in out and len(out) > 1 else None
