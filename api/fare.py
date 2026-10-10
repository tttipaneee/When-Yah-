"""Estimated normal (usual) Grab fare for a route — used ONLY if reports/fare_check.json passed.

fare = max(minimum, base + per_km x km + per_min x minutes) with Grab's published Klang Valley rates
(data/fares/grab_rates.csv, Jan 2023, cited), km/minutes from OpenStreetMap routing (OSRM, free-flow
time). If the fare check fitted a correction factor on Ravin's own off-peak quotes, it is applied.
"""
import csv
import json
import urllib.request
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RATES = ROOT / "data" / "fares" / "grab_rates.csv"
CHECK = ROOT / "reports" / "fare_check.json"
CACHE = ROOT / "data" / "fares" / "route_cache.json"  # routes for demo presets: works offline
OSRM = "https://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=false"


@lru_cache(maxsize=1)
def rates() -> dict:
    with RATES.open(encoding="utf-8") as f:
        return next(csv.DictReader(f))


def _key(a: tuple[float, float], b: tuple[float, float]) -> str:
    return f"{a[0]:.5f},{a[1]:.5f};{b[0]:.5f},{b[1]:.5f}"


def route(a: tuple[float, float], b: tuple[float, float], timeout: float = 4.0) -> tuple[float, float] | None:
    """(km, minutes) from OSRM, or the cache; None if unavailable."""
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    k = _key(a, b)
    if k in cache:
        return tuple(cache[k])
    try:
        url = OSRM.format(lat1=a[0], lon1=a[1], lat2=b[0], lon2=b[1])
        with urllib.request.urlopen(url, timeout=timeout) as r:
            rt = json.load(r)["routes"][0]
    except Exception:
        return None
    return rt["distance"] / 1000, rt["duration"] / 60


def raw_fare(km: float, minutes: float) -> float:
    r = rates()
    return max(float(r["minimum_rm"]), float(r["base_rm"]) + float(r["per_km_rm"]) * km
               + float(r["per_min_rm"]) * minutes)


def check() -> dict:
    return json.loads(CHECK.read_text(encoding="utf-8")) if CHECK.exists() else {"passed": False}


def estimate(a: tuple[float, float], b: tuple[float, float]) -> dict | None:
    """{'rm', 'km', 'min', 'source'} if the fare check passed and a route is available, else None."""
    c = check()
    if not c.get("passed"):
        return None
    rt = route(a, b)
    if rt is None:
        return None
    km, mins = rt
    factor = float(c.get("factor", 1.0))
    src = (f"Grab published rates ({rates()['effective']}, {rates()['source_url']}) + OpenStreetMap route"
           + (f", x{factor:.2f} fitted on our own off-peak quotes (reports/fare_check.md)" if factor != 1.0 else ""))
    return {"rm": round(raw_fare(km, mins) * factor, 2), "km": round(km, 1), "min": round(mins), "source": src}
