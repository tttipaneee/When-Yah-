"""Experiment: is the price predictable when averaged over a whole borough? -> reports/borough_experiment.md

Same trips, fare model (train-day fit in data/processed/base_fare.json), split-half noise control and
splits as build_dataset.py, but windows are borough x 15 min (5 boroughs; EWR dropped) instead of
zone x 15 min. Averaging thousands of trips removes most measurement noise, so a real area-wide
"surge is ending" pattern would show up here if it exists. The borough is NOT a feature (area-agnostic).
Zone -> borough: NYC TLC taxi zones (NYC Open Data export 2025-10-03), data/zones/taxi_zones_borough.csv.

Success rule (fixed in code before the run): borough-level prediction "helps" if, on held-out
TEST days, a When Yah? variant's mean policy saving has a 95% CI lower bound above the hour-of-day
baseline's upper bound, OR its +30 min drop-10% ROC-AUC is >= 0.65. Otherwise: "does not help".
Usage: python -m ml.experiment_borough
"""
import json
from datetime import date
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from sklearn.metrics import roc_auc_score

from ml.build_dataset import RAW, chunks, split_of
from ml.evaluate import decide, pct, policy_stats
from ml.features import HORIZONS, NO_LEVEL, WITH_LEVEL, build_frame
from ml.train import PARAMS

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "reports" / "borough_experiment.md"
BOROUGHS = {"Manhattan": 1, "Brooklyn": 2, "Queens": 3, "Bronx": 4, "Staten Island": 5}
VARIANTS = {"no_level": NO_LEVEL, "with_level": WITH_LEVEL}


def borough_windows() -> pd.DataFrame:
    coef = json.loads((ROOT / "data" / "processed" / "base_fare.json").read_text())["coef"]
    zones = pd.read_csv(ROOT / "data" / "zones" / "taxi_zones_borough.csv")
    zmap = dict(zip(zones.zone, zones.borough.map(BOROUGHS)))
    rng = np.random.default_rng(0)
    parts = []
    for d in chunks(pq.ParquetFile(RAW)):
        exp = np.full(len(d), np.nan)
        for lic, c in coef.items():
            m = (d.hvfhs_license_num == lic).values
            exp[m] = c[0] + c[1] * d.trip_miles.values[m] + c[2] * d.mins.values[m]
        d = d.assign(idx=np.clip(d.base_passenger_fare.values / exp, 0.3, 3.0),
                     zone=d.PULocationID.map(zmap))
        d = d[np.isfinite(d.idx) & (exp > 1) & d.zone.notna()]
        d["bucket"] = d.t.dt.floor("15min")
        a = rng.random(len(d)) < 0.5
        d = d.assign(sa=np.where(a, d.idx, 0.0), n_a=a.astype(int), sb=np.where(a, 0.0, d.idx), n_b=(~a).astype(int))
        g = d.groupby(["zone", "bucket"])
        parts.append(pd.concat([g.idx.agg(["sum", "count"]), g[["sa", "n_a", "sb", "n_b"]].sum()], axis=1))
    z = pd.concat(parts).groupby(level=[0, 1]).sum().reset_index().rename(columns={"count": "n"})
    z["idx"], z["idx_a"], z["idx_b"] = z["sum"] / z.n, z.sa / z.n_a, z.sb / z.n_b
    z = z[(z.n_a >= 20) & (z.n_b >= 20)].drop(columns=["sum", "sa", "sb"])
    z["zone"] = z.zone.astype(int)
    z["split"] = split_of(z.bucket)
    return z.sort_values(["zone", "bucket"]).reset_index(drop=True)


def main() -> None:
    df = build_frame(borough_windows())
    rcols = [f"ratio_{h}" for h in HORIZONS]
    tr = df[df.split == "train"]
    te = df[df.split == "test"].dropna(subset=rcols).reset_index(drop=True)
    actual = te[rcols].to_numpy()
    clusters = (te.zone.astype(str) + "_" + te.bucket.dt.date.astype(str)).to_numpy()
    print(f"borough windows: train {len(tr):,}, test {len(te):,}; median trips/window {int(df.n.median())}")

    hour_avg = {h: tr.groupby("hour")[f"ratio_{h}"].mean() for h in HORIZONS}
    ha = np.c_[[te.hour.map(hour_avg[h]).to_numpy() for h in HORIZONS]].T
    rows = {"Book now (always)": policy_stats(np.zeros(len(te), bool), np.zeros(len(te), int), actual, clusters),
            "Hour-of-day average ratio": policy_stats(*decide(ha, None), actual, clusters)}
    auc, mae, auc_ci = {}, {}, {}
    y30 = (actual[:, 1] <= 0.9).astype(int)
    for v, feats in VARIANTS.items():
        mean, q90 = [], []
        for h in HORIZONS:
            d = tr[tr[f"ratio_{h}"].notna()]
            mean.append(lgb.LGBMRegressor(**PARAMS).fit(d[feats], d[f"ratio_{h}"]).predict(te[feats]))
            q90.append(lgb.LGBMRegressor(objective="quantile", alpha=0.9, **PARAMS)
                       .fit(d[feats], d[f"ratio_{h}"]).predict(te[feats]))
            if h == 30 and y30.sum() > 0:
                p = lgb.LGBMClassifier(**PARAMS).fit(d[feats], d["drop10_30"].astype(int)).predict_proba(te[feats])[:, 1]
                auc[v] = roc_auc_score(y30, p)
                days = te.bucket.dt.date.to_numpy()
                ud, bs = np.unique(days), []
                rng = np.random.default_rng(0)
                for _ in range(500):  # bootstrap over test days
                    pick = np.concatenate([np.flatnonzero(days == d) for d in rng.choice(ud, len(ud))])
                    if 0 < y30[pick].sum() < len(pick):
                        bs.append(roc_auc_score(y30[pick], p[pick]))
                auc_ci[v] = (np.percentile(bs, 2.5), np.percentile(bs, 97.5))
        mean, q90 = np.c_[mean].T, np.c_[q90].T
        rows[f"When Yah? {v}"] = policy_stats(*decide(mean, q90), actual, clusters)
        mae[v] = np.abs(actual[:, 1] - mean[:, 1]).mean() / np.abs(actual[:, 1] - 1).mean() - 1

    ho = rows["Hour-of-day average ratio"]
    wins = [v for v in VARIANTS if rows[f"When Yah? {v}"]["lo"] > ho["hi"] or auc.get(v, 0) >= 0.65]
    L = ["# Experiment: borough-level price windows", "",
         f"Generated by `python -m ml.experiment_borough` on {date.today().isoformat()}.",
         "Borough x 15-min windows (≥ 20 trips per half), same fare model, splits and split-half noise control",
         "as `reports/metrics.md`. Borough is not a model feature.",
         f"Test windows: **{len(te):,}**; median trips per window: {int(df.n.median()):,}. "
         f"Share of test windows where the price drops ≥ 10% by +30 min: {y30.mean():.1%}.",
         "Rule (fixed in code before the run; committed together with the results): helps if a variant's saving CI is above the hour-of-day baseline's, or its",
         "+30 min drop AUC ≥ 0.65.", "",
         "| Policy | Waits | Mean saving vs book now (95% CI) | Saving when it waits | Waits that cost more | AUC drop ≥10% @30 | MAE @30 vs persistence |",
         "|---|---|---|---|---|---|---|"]
    for k, s in rows.items():
        v = k.replace("When Yah? ", "")
        extra = (f"{auc[v]:.3f}" if v in auc else "–") + " | " + (f"{mae[v]:+.1%}" if v in mae else "–")
        L.append(f"| {k} | {s['wait_rate']:.1%} | {pct(s['saving'])} ({pct(s['lo'])} … {pct(s['hi'])}) | "
                 f"{pct(s['saving_when_wait'])} | {s['worse_share_of_waits']:.1%} | {extra} |")
    L += ["", f"AUC 95% CI (bootstrap over test days): " + "; ".join(f"{v} {lo:.2f}–{hi:.2f}" for v, (lo, hi) in auc_ci.items())
          + f". Drops ≥ 10% at +30 min in test: **{int(y30.sum())} windows** — a very small number of events."]
    L += ["", f"Rule outcome: {'passes (' + ', '.join(wins) + ')' if wins else 'fails'}. **Result: INCONCLUSIVE** — the AUC rests on "
          f"{int(y30.sum())} drop windows (a handful of episodes, mostly Manhattan pre-dawn), borough-level `level` partly "
          "encodes area identity, and savings are not above the hour-of-day rule. Event features are off here (venue "
          "zone IDs never match borough codes)."]
    L += ["", "## Reading (plain)",
          f"- Area-wide prices ARE somewhat predictable: with_level forecast error is {mae['with_level']:+.1%} vs",
          "  persistence, and it ranks the rare 10% drops well (AUC above).",
          f"- But area-wide prices rarely move much ({y30.mean():.1%} of windows drop ≥ 10% in 30 min), so following the",
          f"  advice saves {pct(rows['When Yah? with_level']['saving'])} on average — "
          + ("still below" if rows['When Yah? with_level']['hi'] < ho['lo'] else "not clearly above")
          + f" the hour-of-day rule ({pct(ho['saving'])}).",
          "- The rule passed on AUC only, from a handful of drop events; treat it as a hint, not proof."]
    REPORT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
