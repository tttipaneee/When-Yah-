"""Real Aug 2024 NYC venue events -> data/events/nyc_events_2024-08.csv (every row has a source_url).

- Yankee Stadium / Citi Field: MLB home games from statsapi.mlb.com (first pitch + game duration, so
  start/end are real). Postponed games are dropped (they reappear as the makeup game).
- Madison Square Garden / Barclays Center: concerts listed on setlist.fm for Aug 2024. No sourced
  start/end time exists, so start/end are left empty and these rows are NOT used for timing features.
Zone IDs: venue coordinates matched point-in-polygon to NYC TLC taxi zones (NYC Open Data, 2025 file).
Usage: python ml/fetch_nyc_events.py
"""
import csv
import json
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

OUT = Path(__file__).resolve().parent.parent / "data" / "events" / "nyc_events_2024-08.csv"
NY = ZoneInfo("America/New_York")
VENUES = {  # name: (TLC zone id, lat, lon)
    "Yankee Stadium": (247, 40.8296, -73.9262),
    "Citi Field": (93, 40.7571, -73.8458),
    "Madison Square Garden": (186, 40.7505, -73.9934),
    "Barclays Center": (181, 40.6826, -73.9754),
}
TEAMS = {147: "Yankee Stadium", 121: "Citi Field"}
SETLISTS = [  # (date, name, venue, source_url) — from setlist.fm venue search, Aug 2024
    ("2024-08-12", "Orbit Culture", "Madison Square Garden",
     "https://www.setlist.fm/setlist/orbit-culture/2024/madison-square-garden-new-york-ny-ba9bd6a.html"),
    ("2024-08-27", "Young Miko (The Theater at MSG)", "Madison Square Garden",
     "https://www.setlist.fm/setlist/young-miko/2024/madison-square-garden-the-theater-at-madison-square-garden-new-york-ny-43575b87.html"),
    ("2024-08-12", "Ciara", "Barclays Center",
     "https://www.setlist.fm/setlist/ciara/2024/barclays-center-brooklyn-ny-1b550914.html"),
    ("2024-08-27", "Childish Gambino", "Barclays Center",
     "https://www.setlist.fm/setlist/childish-gambino/2024/barclays-center-brooklyn-ny-6ba91296.html"),
]


def get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


def mlb_rows() -> list[dict]:
    rows = []
    for team, venue in TEAMS.items():
        sched = get(f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId={team}"
                    "&startDate=2024-07-31&endDate=2024-09-01")
        for d in sched["dates"]:
            for g in d["games"]:
                if g["venue"]["name"] != venue or g["status"]["detailedState"] != "Final":
                    continue
                pk = g["gamePk"]
                url = f"https://statsapi.mlb.com/api/v1.1/game/{pk}/feed/live"
                info = get(url + "?fields=gameData,gameInfo,firstPitch,gameDurationMinutes,attendance")
                info = info["gameData"]["gameInfo"]
                start = datetime.fromisoformat(info["firstPitch"].replace("Z", "+00:00")).astimezone(NY)
                end = start + timedelta(minutes=info["gameDurationMinutes"])
                zone, lat, lon = VENUES[venue]
                away = g["teams"]["away"]["team"]["name"]
                rows.append(dict(id=f"mlb-{pk}", name=f"MLB: {away} at {g['teams']['home']['team']['name']}",
                                 venue=venue, zone_id=zone, lat=lat, lon=lon, date=start.date().isoformat(),
                                 start=start.isoformat(), end=end.isoformat(),
                                 attendance=info.get("attendance", ""), source_url=url))
    return rows


def main() -> None:
    rows = mlb_rows()
    for i, (day, name, venue, url) in enumerate(SETLISTS):
        zone, lat, lon = VENUES[venue]
        rows.append(dict(id=f"setlist-{i}", name=name, venue=venue, zone_id=zone, lat=lat, lon=lon,
                         date=day, start="", end="", attendance="", source_url=url))
    rows.sort(key=lambda r: (r["date"], r["start"]))
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    timed = sum(1 for r in rows if r["start"])
    print(f"wrote {len(rows)} events ({timed} with sourced start/end) -> {OUT}")


if __name__ == "__main__":
    main()
