"""Hourly observed weather, NY City Central Park (NOAA ISD station 72505394728 / KNYC), Aug 2024
-> data/weather/nyc_central_park_2024-08.csv

Source (NOAA NCEI Global Hourly / ISD, accessed 10 Oct 2026):
  https://www.ncei.noaa.gov/access/services/data/v1?dataset=global-hourly&stations=72505394728
  &startDate=2024-07-31&endDate=2024-09-02&format=csv&dataTypes=TMP,DEW,AA1
(Open-Meteo archive was rate-limited from this network; NOAA station observations are used instead.)

Only routine hourly METAR reports (FM-15) are kept. precip_mm = AA1 liquid depth over the past hour;
rain = precip_mm > 0. rh = relative humidity from temperature and dew point (Magnus formula).
`obs_time` is when the report was issued (UTC); features must use the last report at or before t.
Usage: python ml/fetch_weather.py
"""
import io
import math
import urllib.request
from pathlib import Path

import pandas as pd

URL = ("https://www.ncei.noaa.gov/access/services/data/v1?dataset=global-hourly&stations=72505394728"
       "&startDate=2024-07-31&endDate=2024-09-02&format=csv&dataTypes=TMP,DEW,AA1")
OUT = Path(__file__).resolve().parent.parent / "data" / "weather" / "nyc_central_park_2024-08.csv"


def _val(s: str, scale: float = 10.0) -> float:
    """ISD '+0250,5' -> 25.0 (missing = +9999)."""
    if not isinstance(s, str):
        return math.nan
    v = s.split(",")[0]
    return math.nan if v.lstrip("+-") in ("9999", "99999") else int(v) / scale


def _precip(s: str) -> float:
    """AA1 'hours,depth(0.1mm),cond,qual'; only 1-hour periods."""
    if not isinstance(s, str):
        return math.nan
    p = s.split(",")
    if p[0] != "01" or p[1] == "9999":
        return math.nan
    return int(p[1]) / 10.0


def rh(t: float, td: float) -> float:
    a, b = 17.625, 243.04
    return 100 * math.exp(a * td / (b + td) - a * t / (b + t))


def main() -> None:
    with urllib.request.urlopen(URL, timeout=120) as r:
        raw = pd.read_csv(io.BytesIO(r.read()), dtype=str)
    raw = raw[raw.REPORT_TYPE.str.strip() == "FM-15"]
    df = pd.DataFrame({
        "obs_time": pd.to_datetime(raw.DATE).dt.tz_localize("UTC"),
        "temp_c": raw.TMP.map(_val),
        "dew_c": raw.DEW.map(_val),
        "precip_mm": raw.AA1.map(_precip),
    })
    df["precip_mm"] = df.precip_mm.fillna(0.0)  # FM-15 without AA1 = no measurable precipitation
    df["rh"] = [rh(t, d) if not (math.isnan(t) or math.isnan(d)) else math.nan
                for t, d in zip(df.temp_c, df.dew_c)]
    df["rain"] = (df.precip_mm > 0).astype(int)
    df = df.dropna(subset=["temp_c"]).sort_values("obs_time")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.round({"temp_c": 2, "dew_c": 2, "precip_mm": 2, "rh": 2}).to_csv(OUT, index=False)
    print(f"wrote {len(df)} hourly reports, {df.rain.sum()} with rain -> {OUT}")


if __name__ == "__main__":
    main()
