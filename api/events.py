"""Real Malaysian events from data/events/malaysia_events.csv (every row has a source_url)."""
import csv
import math
from datetime import date, datetime
from pathlib import Path

from api.schemas import Event

CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "events" / "malaysia_events.csv"
NEARBY_KM = 5.0


def load_events() -> list[Event]:
    if not CSV_PATH.exists():
        return []
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        return [Event(**{**row, "end": row.get("end") or None})
                for row in csv.DictReader(f) if row.get("source_url")]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def events_on(day: date, lat: float | None = None, lon: float | None = None) -> list[Event]:
    """Events on `day` (local date); if a pickup is given, only those within NEARBY_KM."""
    out = [e for e in load_events() if e.start.date() <= day <= (e.end or e.start).date()]
    if lat is not None and lon is not None:
        out = [e for e in out if haversine_km(lat, lon, e.lat, e.lon) <= NEARBY_KM]
    return sorted(out, key=lambda e: e.start)


def events_near(ts: datetime, lat: float | None, lon: float | None) -> list[Event]:
    return events_on(ts.date(), lat, lon)
