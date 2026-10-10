"""Build the zone x 15-min price-index dataset from NYC HVFHV Aug 2024 (row group by row group).

Price index = base_passenger_fare / expected fare for the trip's miles and minutes. Expected fare is a
linear fit per company (HV0003 Uber, HV0005 Lyft) on TRAIN days only. Trip index clipped to [0.3, 3],
averaged per pickup zone x 15-min request window; windows with < MIN_TRIPS trips are dropped.
Each trip is also assigned at random (seeded) to half A or half B, and the index is averaged per half:
the model sees the level from half A and is scored on half B, so sampling noise in a window's average
cannot be both the input and the outcome (leakage audit finding 1). Windows need >= MIN_HALF per half.
Split by day (no shuffling): train Aug 1-21, val Aug 22-25, test Aug 26-31.

Outputs: data/processed/windows.parquet (zone, bucket, idx, n, split), data/processed/base_fare.json
Usage: python ml/build_dataset.py [data/raw/fhvhv_tripdata_2024-08.parquet]
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "fhvhv_tripdata_2024-08.parquet"
OUT = ROOT / "data" / "processed"
COLS = ["hvfhs_license_num", "request_datetime", "PULocationID", "trip_miles", "trip_time",
        "base_passenger_fare"]
MIN_TRIPS = 8
MIN_HALF = 4
SPLITS = [("train", "2024-08-01", "2024-08-22"), ("val", "2024-08-22", "2024-08-26"),
          ("test", "2024-08-26", "2024-09-01")]


def split_of(ts: pd.Series) -> pd.Series:
    out = pd.Series(pd.NA, index=ts.index, dtype="object")
    for name, a, b in SPLITS:
        out[(ts >= a) & (ts < b)] = name
    return out


def chunks(pf: pq.ParquetFile):
    for i in range(pf.num_row_groups):
        d = pf.read_row_group(i, columns=COLS).to_pandas().dropna()
        d = d[(d.base_passenger_fare > 0) & (d.trip_miles > 0.2) & (d.trip_time > 60)]
        d["t"] = pd.to_datetime(d.request_datetime)  # naive NYC local time
        d["split"] = split_of(d.t)
        d = d[d.split.notna()]
        d["mins"] = d.trip_time / 60.0
        yield d


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else RAW
    pf = pq.ParquetFile(path)
    OUT.mkdir(parents=True, exist_ok=True)

    sums = {}
    for d in chunks(pf):
        tr = d[d.split == "train"]
        for lic, g in tr.groupby("hvfhs_license_num", observed=True):
            X = np.c_[np.ones(len(g)), g.trip_miles.values, g.mins.values]
            a, b = sums.get(lic, (np.zeros((3, 3)), np.zeros(3)))
            sums[lic] = (a + X.T @ X, b + X.T @ g.base_passenger_fare.values)
    coef = {lic: np.linalg.solve(a, b).tolist() for lic, (a, b) in sums.items()}
    for lic, c in coef.items():
        print(f"{lic}: fare ~ {c[0]:.2f} + {c[1]:.2f}*miles + {c[2]:.2f}*min (train days)")
    (OUT / "base_fare.json").write_text(json.dumps({"fit_on": "train days Aug 1-21 2024", "coef": coef}, indent=1))

    parts, n_trips = [], 0
    rng = np.random.default_rng(0)
    for d in chunks(pf):
        exp = np.full(len(d), np.nan)
        for lic, c in coef.items():
            m = (d.hvfhs_license_num == lic).values
            exp[m] = c[0] + c[1] * d.trip_miles.values[m] + c[2] * d.mins.values[m]
        d = d.assign(idx=np.clip(d.base_passenger_fare.values / exp, 0.3, 3.0))
        d = d[np.isfinite(d.idx) & (exp > 1)]
        n_trips += len(d)
        d["bucket"] = d.t.dt.floor("15min")
        half_a = rng.random(len(d)) < 0.5
        d = d.assign(sa=np.where(half_a, d.idx, 0.0), na=half_a.astype(int),
                     sb=np.where(half_a, 0.0, d.idx), nb=(~half_a).astype(int))
        g = d.groupby(["PULocationID", "bucket"])
        parts.append(pd.concat([g.idx.agg(["sum", "count"]), g[["sa", "na", "sb", "nb"]].sum()], axis=1))
    z = pd.concat(parts).groupby(level=[0, 1]).sum().reset_index()
    z = z.rename(columns={"PULocationID": "zone", "count": "n", "na": "n_a", "nb": "n_b"})
    z["idx"] = z["sum"] / z["n"]
    z["idx_a"] = z.sa / z.n_a.where(z.n_a > 0)
    z["idx_b"] = z.sb / z.n_b.where(z.n_b > 0)
    z = z[(z.n >= MIN_TRIPS) & (z.n_a >= MIN_HALF) & (z.n_b >= MIN_HALF)].drop(columns=["sum", "sa", "sb"])
    z["split"] = split_of(z.bucket)
    z = z.sort_values(["zone", "bucket"]).reset_index(drop=True)
    z.to_parquet(OUT / "windows.parquet", index=False)
    print(f"trips used: {n_trips:,}; windows (>= {MIN_TRIPS} trips, >= {MIN_HALF} per half): {len(z):,} in {z.zone.nunique()} zones")
    print(z.groupby("split").agg(windows=("idx", "size"), days=("bucket", lambda s: s.dt.date.nunique())))


if __name__ == "__main__":
    main()
