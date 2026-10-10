"""Go/no-go signal check for NYC High Volume FHV (Uber/Lyft) trip records.

Price index = base_passenger_fare / expected fare for that trip's miles and minutes
(expected fare fitted per company on the first 70% of days only).
Aggregates the median index per pickup zone x 15-minute request window, then reports:
  - share of variance explained by hour x weekday
  - lag autocorrelation of the zone-level index (15/30/60 min)
  - how often the index changes by >=10% within 15/30/60 minutes
  - how much a model using only past index + time beats persistence (quick LightGBM-free check)
Usage: python check_signal_nyc.py <fhvhv_tripdata.parquet> [min_trips_per_window]
"""
import sys
import numpy as np
import pandas as pd

path = sys.argv[1]
min_trips = int(sys.argv[2]) if len(sys.argv) > 2 else 8

cols = ["hvfhs_license_num", "request_datetime", "PULocationID", "trip_miles", "trip_time", "base_passenger_fare"]
import pyarrow.parquet as pq
tbl = pq.read_table(path, columns=cols)
tbl = tbl.set_column(0, "hvfhs_license_num", tbl.column(0).dictionary_encode())
df = tbl.to_pandas()
del tbl
df = df.dropna()
df = df[(df.base_passenger_fare > 0) & (df.trip_miles > 0.2) & (df.trip_time > 60)]
df["t"] = pd.to_datetime(df.request_datetime)
df["day"] = df.t.dt.floor("D")
days = np.sort(df.day.unique())
cut = days[int(len(days) * 0.7)]
print(f"rows={len(df):,} days={len(days)} range={df.t.min()} .. {df.t.max()} train_cut={cut}")

# expected fare per company: linear in miles and minutes, fitted on training days only
df["mins"] = df.trip_time / 60.0
df["expected"] = np.nan
for lic, g in df.groupby("hvfhs_license_num"):
    tr = g[g.day < cut]
    X = np.c_[np.ones(len(tr)), tr.trip_miles, tr.mins]
    coef, *_ = np.linalg.lstsq(X, tr.base_passenger_fare.values, rcond=None)
    Xa = np.c_[np.ones(len(g)), g.trip_miles, g.mins]
    df.loc[g.index, "expected"] = Xa @ coef
    print(f"{lic}: fare ~ {coef[0]:.2f} + {coef[1]:.2f}*miles + {coef[2]:.2f}*min (train days)")
df = df[df.expected > 1]
df["idx"] = df.base_passenger_fare / df.expected

df["bucket"] = df.t.dt.floor("15min")
z = df.groupby(["PULocationID", "bucket"]).agg(idx=("idx", "median"), n=("idx", "size")).reset_index()
z = z[z.n >= min_trips]
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

# quick predictability: does (hour, dow) mean + current index beat persistence for +30 min on test days?
z = z.sort_values(["PULocationID", "bucket"])
z["fut30"] = z.groupby("PULocationID").idx.shift(-2)
z["gap_ok"] = z.groupby("PULocationID").bucket.shift(-2) == z.bucket + pd.Timedelta("30min")
zz = z[z.gap_ok & z.fut30.notna()].copy()
tr, te = zz[zz.bucket < cut], zz[zz.bucket >= cut]
hm = tr.groupby(["hour", "dow"]).fut30.mean().rename("hm")
te = te.join(hm, on=["hour", "dow"])
X = np.c_[np.ones(len(tr)), tr.idx, tr.join(hm, on=["hour", "dow"]).hm]
coef, *_ = np.linalg.lstsq(X, tr.fut30.values, rcond=None)
pred = np.c_[np.ones(len(te)), te.idx, te.hm.fillna(tr.fut30.mean())] @ coef
print(f"+30 min test MAE: persistence={np.mean(np.abs(te.fut30 - te.idx)):.4f}  "
      f"hour-avg={np.mean(np.abs(te.fut30 - te.hm.fillna(tr.fut30.mean()))):.4f}  "
      f"simple model={np.mean(np.abs(te.fut30 - pred)):.4f}  (n={len(te):,})")
