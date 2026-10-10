"""Experiment: do live-traffic features (jam level, jam clearing) improve the forecast, and can the model
say WHY a price is high? -> reports/traffic_experiment.md

Traffic features from ml/traffic.py (borough of the pickup zone, trips finished before t only):
congestion = speed now / free-flow speed; congestion_trend = speed now / speed 15 min earlier.

Rules (fixed in code before the run; committed together with the results; B revised after the re-audit):
 A. Forecast: traffic HELPS if, on TEST days, a traffic variant's mean policy saving has a 95% CI lower bound
    above the hour-of-day baseline's upper bound, OR its +30 min drop-10% AUC beats the same model without
    traffic by >= 0.03 with a day-bootstrap 95% CI of the difference above 0.
 B. "Why is it high": traffic explains the level only if a model with time, rain, events, BOROUGH and traffic
    beats the same model without traffic by >= 0.05 test R^2 (re-audit: R^2 alone was an area proxy).
Usage: python -m ml.experiment_traffic
"""
from datetime import date
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import r2_score, roc_auc_score

from ml.evaluate import decide, pct, policy_stats
from ml.features import BASE, EVENT, HORIZONS, NO_LEVEL, WITH_LEVEL
from ml.traffic import zone_borough
from ml.train import PARAMS, load_frame

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "reports" / "traffic_experiment.md"
TRAFFIC = ["congestion", "congestion_trend"]
VARIANTS = {"no_level": NO_LEVEL, "traffic_only": NO_LEVEL + TRAFFIC,
            "with_level": WITH_LEVEL, "level_traffic": WITH_LEVEL + TRAFFIC}
PAIRS = [("traffic_only", "no_level"), ("level_traffic", "with_level")]


def load() -> pd.DataFrame:
    df = load_frame()
    df["borough"] = df.zone.map(zone_borough())
    t = pd.read_parquet(ROOT / "data" / "processed" / "traffic.parquet")
    return df.merge(t[["borough", "bucket"] + TRAFFIC], on=["borough", "bucket"], how="left")


def main() -> None:
    df = load()
    rcols = [f"ratio_{h}" for h in HORIZONS]
    tr = df[(df.split == "train") & df.congestion.notna()]
    te = df[(df.split == "test") & df.congestion.notna()].dropna(subset=rcols).reset_index(drop=True)
    actual = te[rcols].to_numpy()
    days = te.bucket.dt.date.to_numpy()
    clusters = (te.zone.astype(str) + "_" + days.astype(str))
    y30 = (actual[:, 1] <= 0.9).astype(int)
    print(f"train {len(tr):,} test {len(te):,}")

    hour_avg = {h: tr.groupby("hour")[f"ratio_{h}"].mean() for h in HORIZONS}
    ha = np.c_[[te.hour.map(hour_avg[h]).to_numpy() for h in HORIZONS]].T
    rows = {"Book now (always)": policy_stats(np.zeros(len(te), bool), np.zeros(len(te), int), actual, clusters),
            "Hour-of-day average ratio": policy_stats(*decide(ha, None), actual, clusters)}
    p30, mae = {}, {}
    for v, feats in VARIANTS.items():
        mean, q90 = [], []
        for h in HORIZONS:
            d = tr[tr[f"ratio_{h}"].notna()]
            mean.append(lgb.LGBMRegressor(**PARAMS).fit(d[feats], d[f"ratio_{h}"]).predict(te[feats]))
            q90.append(lgb.LGBMRegressor(objective="quantile", alpha=0.9, **PARAMS)
                       .fit(d[feats], d[f"ratio_{h}"]).predict(te[feats]))
            if h == 30:
                p30[v] = lgb.LGBMClassifier(**PARAMS).fit(d[feats], d["drop10_30"].astype(int)) \
                    .predict_proba(te[feats])[:, 1]
        mean, q90 = np.c_[mean].T, np.c_[q90].T
        rows[f"When Yah? {v}"] = policy_stats(*decide(mean, q90), actual, clusters)
        mae[v] = np.abs(actual[:, 1] - mean[:, 1]).mean() / np.abs(actual[:, 1] - 1).mean() - 1
        print("trained", v)
    auc = {v: roc_auc_score(y30, p) for v, p in p30.items()}

    rng, ud = np.random.default_rng(0), np.unique(days)
    diff_ci = {}
    for a, b in PAIRS:
        bs = []
        for _ in range(300):
            pick = np.concatenate([np.flatnonzero(days == d) for d in rng.choice(ud, len(ud))])
            bs.append(roc_auc_score(y30[pick], p30[a][pick]) - roc_auc_score(y30[pick], p30[b][pick]))
        diff_ci[a] = (auc[a] - auc[b], np.percentile(bs, 2.5), np.percentile(bs, 97.5))

    ho = rows["Hour-of-day average ratio"]
    wins_a = [a for a, _ in PAIRS if rows[f"When Yah? {a}"]["lo"] > ho["hi"]
              or (diff_ci[a][0] >= 0.03 and diff_ci[a][1] > 0)]

    # B. why is the price high: level ~ time, rain, events, traffic
    why_feats = BASE + EVENT + TRAFFIC
    trl = tr.dropna(subset=["level"])
    lm = lgb.LGBMRegressor(**PARAMS).fit(trl[why_feats], trl.level)
    r2 = r2_score(te.level, lm.predict(te[why_feats]))
    r2_time = r2_score(te.level, lgb.LGBMRegressor(**PARAMS).fit(trl[BASE], trl.level).predict(te[BASE]))
    area = BASE + EVENT + ["borough"]
    r2_area = r2_score(te.level, lgb.LGBMRegressor(**PARAMS).fit(trl[area], trl.level).predict(te[area]))
    r2_area_tr = r2_score(te.level, lgb.LGBMRegressor(**PARAMS).fit(trl[area + TRAFFIC], trl.level)
                          .predict(te[area + TRAFFIC]))
    rho = trl[["level", "congestion"]].corr(method="spearman").iloc[0, 1]
    hi = te[te.level >= 1.5]
    contrib = pd.DataFrame(lm.predict(hi[why_feats], pred_contrib=True)[:, :-1], columns=why_feats)
    explained = (lm.predict(hi[why_feats]) - 1).mean()
    actual_excess = (hi.level - 1).mean()
    win_b = r2_area_tr - r2_area >= 0.05

    L = ["# Experiment: traffic features (jam level, jam clearing) and 'why is it high'", "",
         f"Generated by `python -m ml.experiment_traffic` on {date.today().isoformat()}.",
         "Traffic from the trips themselves (`ml/traffic.py`): per borough of the pickup zone, speed of trips that",
         "had already finished before t. congestion = speed ÷ free-flow speed (95th pct, train days);",
         "congestion_trend = speed now ÷ speed 15 min earlier (> 1 = clearing). Same splits and split-half noise",
         f"control as `reports/metrics.md`. Test windows: **{len(te):,}**.", "",
         "## A. Does traffic improve the forecast?",
         "Rule (fixed in code before the run; committed together with the results): saving CI above the hour-of-day baseline's, or +30 min AUC ≥ 0.03 higher than",
         "the same model without traffic with a day-bootstrap CI above 0.", "",
         "| Policy | Waits | Mean saving vs book now (95% CI) | Waits that cost more | AUC drop ≥10% @30 | MAE @30 vs persistence |",
         "|---|---|---|---|---|---|"]
    for k, s in rows.items():
        v = k.replace("When Yah? ", "")
        extra = f"{auc[v]:.3f} | {mae[v]:+.1%}" if v in auc else "– | –"
        L.append(f"| {k} | {s['wait_rate']:.1%} | {pct(s['saving'])} ({pct(s['lo'])} … {pct(s['hi'])}) | "
                 f"{s['worse_share_of_waits']:.1%} | {extra} |")
    L += [""] + [f"- AUC gain from traffic, {a} vs {b}: {diff_ci[a][0]:+.3f} (95% CI {diff_ci[a][1]:+.3f} … {diff_ci[a][2]:+.3f})"
                 for a, b in PAIRS]
    L += ["", f"**Result A: traffic {'HELPS (' + ', '.join(wins_a) + ')' if wins_a else 'does NOT help'} the forecast.**", "",
          "## B. Can the model say why a price is high?",
          "Model of the current level (price ÷ expected) from time, rain, events and traffic, trained on train days.",
          "Rule (fixed in code before the run, revised after the re-audit): traffic must add ≥ 0.05 test R² over",
          "time + rain + events + borough.", "",
          f"- Test R²: time + rain {r2_time:.3f}; + events + traffic {r2:.3f}; + events + borough {r2_area:.3f}; "
          f"+ events + borough + traffic **{r2_area_tr:.3f}** (gain from traffic {r2_area_tr - r2_area:+.3f}).",
          f"- Spearman(level, congestion) on train: {rho:+.2f} (slower traffic goes with a higher level).",
          f"- Windows priced ≥ 1.5× expected ({len(hi):,} in test): actual excess {actual_excess:+.0%} on average; the model",
          f"  explains {explained:+.0%} of it. Mean contributions: "
          + ", ".join(f"{c} {contrib[c].mean():+.3f}" for c in contrib.columns if abs(contrib[c].mean()) >= 0.001) + ".",
          "", f"**Result B: {'the model CAN attribute' if win_b else 'the model can NOT usefully attribute'} a high price to "
          "time / rain / events / traffic.**"]
    L += ["", f"Traffic's apparent R² is mostly area identity (Manhattan is pricier and slower). On prices ≥ 1.5× expected,",
          f"time/rain/events/traffic explain {explained:+.0%} of a {actual_excess:+.0%} excess. **App decision:** never tell users",
          "\"your price is high because of the jam / rain\"."]
    if not win_b:
        L += ["Most of a high price is not explained by anything we can observe (demand and driver supply are not",
              "in the data), so the app must not claim \"high because of the jam / rain\"."]
    REPORT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
