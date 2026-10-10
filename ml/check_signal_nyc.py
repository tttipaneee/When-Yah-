"""Go/no-go signal check for NYC High Volume FHV (Uber/Lyft) trip records — low-memory, chunked.

Price index = base_passenger_fare / expected fare for that trip's miles and minutes.
Expected fare: linear in miles and minutes, fitted per company on the first 70% of days only.
Index is clipped to [0.3, 3] and averaged per pickup zone x 15-minute request window.
Reports:
  - variance explained by hour x weekday, mean index by hour
  - lag correlation of the zone index at +15/30/60 min, share of >=10% changes
  - +30 min test MAE: persistence vs hour-of-day average vs a simple linear model (test = last 30% of days)
Usage: python ml/check_signal_nyc.py <fhvhv_tripdata.parquet> [min_trips_per_window]
"""
import sys
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

path = sys.argv[1]
min_trips = int(sys.argv[2]) if len(sys.argv) > 2 else 8
COLS = ["hvfhs_license_num", "request_datetime", "PULocationID", "trip_miles", "trip_time", "base_passenger_fare"]
pf = pq.ParquetFile(path)


def chunks():
    for i in range(pf.num_row_groups):
        d = pf.read_row_group(i, columns=COLS).to_pandas()
        d = d.dropna()
        d = d[(d.base_passenger_fare > 0) & (d.trip_miles > 0.2) & (d.trip_time > 60)]
        d["t"] = pd.to_datetime(d.request_datetime)
        d["day"] = d.t.dt.floor("D")
        d["mins"] = d.trip_time / 60.0
        yield d


# pass 0: days
days = set()
for i in range(pf.num_row_groups):
    s = pf.read_row_group(i, columns=["request_datetime"]).column(0).to_pandas()
    days.update(pd.to_datetime(s).dt.floor("D").unique())
days = np.array(sorted(days))
cut = days[int(len(days) * 0.7)]
print(f"rows={pf.metadata.num_rows:,} days={len(days)} {days[0]} .. {days[-1]} train_cut={cut}")

# pass 1: regression sums on training days
sums = {}
for d in chunks():
    tr = d[d.day < cut]
    for lic, g in tr.groupby("hvfhs_license_num", observed=True):
        X = np.c_[np.ones(len(g)), g.trip_miles.values, g.mins.values]
        y = g.base_passenger_fare.values
        a, b = sums.get(lic, (np.zeros((3, 3)), np.zeros(3)))
        sums[lic] = (a + X.T @ X, b + X.T @ y)
coef = {lic: np.linalg.solve(a, b) for lic, (a, b) in sums.items()}
for lic, c in coef.items():
    print(f"{lic}: fare ~ {c[0]:.2f} + {c[1]:.2f}*miles + {c[2]:.2f}*min (train days)")

# pass 2: zone x 15-min aggregates
parts = []
for d in chunks():
    exp = np.full(len(d), np.nan)
    for lic, c in coef.items():
        m = (d.hvfhs_license_num == lic).values
        exp[m] = c[0] + c[1] * d.trip_miles.values[m] + c[2] * d.mins.values[m]
    d = d.assign(idx=np.clip(d.base_passenger_fare.values / exp, 0.3, 3.0))
    d = d[np.isfinite(d.idx) & (exp > 1)]
    d["bucket"] = d.t.dt.floor("15min")
    parts.append(d.groupby(["PULocationID", "bucket"]).idx.agg(["sum", "count"]))
z = pd.concat(parts).groupby(level=[0, 1]).sum().reset_index()
z["idx"] = z["sum"] / z["count"]
z = z[z["count"] >= min_trips]
print(f"zone x 15-min windows with >= {min_trips} trips: {len(z):,} across {z.PULocationID.nunique()} zones")

z["hour"] = z.bucket.dt.hour
z["dow"] = z.bucket.dt.dayofweek
m = z.groupby(["hour", "dow"]).idx.transform("mean")
r2 = 1 - ((z.idx - m) ** 2).sum() / ((z.idx - z.idx.mean()) ** 2).sum()
print(f"variance of zone index explained by hour x weekday: {r2:.3f}")
print("mean index by hour:", z.groupby("hour").idx.mean().round(3).to_dict())

res = []
for zone, g in z.groupby("PULocationID"):
    s = g.set_index("bucket").idx.asfreq("15min")
    for h in (1, 2, 4):
        f = s.shift(-h)
        ok = s.notna() & f.notna()
        if ok.sum() < 30:
            continue
        res.append(dict(h=h * 15, n=int(ok.sum()), corr=np.corrcoef(s[ok], f[ok])[0, 1],
                        ch10=float(((f[ok] / s[ok] - 1).abs() >= 0.10).mean()),
                        mae_persist=float((f[ok] - s[ok]).abs().mean())))
r = pd.DataFrame(res)
for h, g in r.groupby("h"):
    w = g.n / g.n.sum()
    print(f"+{h} min: lag corr={np.nansum(g['corr'] * w):.3f}  share changing >=10%={np.sum(g.ch10 * w):.3f}  "
          f"persistence MAE={np.sum(g.mae_persist * w):.4f}  windows={g.n.sum():,}")

z = z.sort_values(["PULocationID", "bucket"])
z["fut30"] = z.groupby("PULocationID").idx.shift(-2)
z["gap_ok"] = z.groupby("PULocationID").bucket.shift(-2) == z.bucket + pd.Timedelta("30min")
zz = z[z.gap_ok & z.fut30.notna()].copy()
tr, te = zz[zz.bucket < cut], zz[zz.bucket >= cut]
hm = tr.groupby(["hour", "dow"]).fut30.mean().rename("hm")
te = te.join(hm, on=["hour", "dow"])
fill = tr.fut30.mean()
X = np.c_[np.ones(len(tr)), tr.idx, tr.join(hm, on=["hour", "dow"]).hm]
c, *_ = np.linalg.lstsq(X, tr.fut30.values, rcond=None)
pred = np.c_[np.ones(len(te)), te.idx, te.hm.fillna(fill)] @ c
print(f"+30 min test MAE: persistence={np.mean(np.abs(te.fut30 - te.idx)):.4f}  "
      f"hour-avg={np.mean(np.abs(te.fut30 - te.hm.fillna(fill))):.4f}  "
      f"simple model={np.mean(np.abs(te.fut30 - pred)):.4f}  (n={len(te):,})")
