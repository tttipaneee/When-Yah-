"""NYC traffic features from the trips themselves -> data/processed/traffic.parquet

Speed of a trip = trip_miles / trip_time. Per borough (of the pickup zone) and 15-min DROPOFF window,
speed = total miles / total hours of trips that finished in that window. Features for decision time t
(window start) use only trips that had already finished:
  speed_now  = trips dropped off in [t-15, t)
  speed_prev = trips dropped off in [t-30, t-15)
  congestion       = speed_now / free_flow   (free_flow = borough's 95th pct of 15-min speeds, TRAIN days)
  congestion_trend = speed_now / speed_prev  (> 1: traffic is clearing, < 1: getting worse)
`congestion` matches what live traffic APIs report (current speed / free-flow speed, e.g. TomTom flow API).
Usage: python -m ml.traffic
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from ml.build_dataset import RAW

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "processed" / "traffic.parquet"
BOROUGHS = {"Manhattan": 1, "Brooklyn": 2, "Queens": 3, "Bronx": 4, "Staten Island": 5}
COLS = ["PULocationID", "dropoff_datetime", "trip_miles", "trip_time"]


def zone_borough() -> dict[int, int]:
    z = pd.read_csv(ROOT / "data" / "zones" / "taxi_zones_borough.csv")
    return {int(k): BOROUGHS[v] for k, v in zip(z.zone, z.borough) if v in BOROUGHS}


def main() -> None:
    zb = zone_borough()
    pf = pq.ParquetFile(RAW)
    parts = []
    for i in range(pf.num_row_groups):
        d = pf.read_row_group(i, columns=COLS).to_pandas().dropna()
        d = d[(d.trip_miles > 0.2) & (d.trip_time > 60)]
        d["borough"] = d.PULocationID.map(zb)
        d = d[d.borough.notna()]
        mph = d.trip_miles / (d.trip_time / 3600)
        d = d[(mph > 1) & (mph < 70)]
        d["bucket"] = pd.to_datetime(d.dropoff_datetime).dt.floor("15min")
        d["hours"] = d.trip_time / 3600
        parts.append(d.groupby(["borough", "bucket"])[["trip_miles", "hours"]].sum())
    s = pd.concat(parts).groupby(level=[0, 1]).sum().reset_index()
    s["speed"] = s.trip_miles / s.hours
    s["borough"] = s.borough.astype(int)

    train = s[(s.bucket >= "2024-08-01") & (s.bucket < "2024-08-22")]
    free = train.groupby("borough").speed.quantile(0.95).rename("free_flow")
    key = s.set_index(["borough", "bucket"]).speed
    out = s[["borough", "bucket"]].copy()
    out["bucket"] = out.bucket + pd.Timedelta(minutes=15)  # trips finished in [b, b+15) are known at b+15
    out["speed_now"] = s.speed.to_numpy()
    prev = pd.MultiIndex.from_arrays([s.borough, s.bucket - pd.Timedelta(minutes=15)])
    out["speed_prev"] = key.reindex(prev).to_numpy()
    out = out.join(free, on="borough")
    out["congestion"] = out.speed_now / out.free_flow
    out["congestion_trend"] = out.speed_now / out.speed_prev
    out.to_parquet(OUT, index=False)
    print(f"traffic windows: {len(out):,}; free-flow mph by borough (train): {free.round(1).to_dict()}")
    print(out.congestion.describe().round(3).to_dict())


if __name__ == "__main__":
    main()
