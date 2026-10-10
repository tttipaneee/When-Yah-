"""Evaluate on held-out TEST days (Aug 26-31 2024) -> reports/metrics.md

1. Policy savings: When Yah? advice (API rule) vs "book now" vs "hour-of-day average ratio".
2. P(drop >= 10%) quality: ROC-AUC, precision/recall at the val-tuned threshold, Brier, calibration.
3. Forecast error: MAE of ratio vs persistence (ratio = 1) and vs hour-of-day average.
Usage: python ml/evaluate.py
"""
import json
import subprocess
from datetime import date
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, precision_score, recall_score, roc_auc_score

from ml.features import HORIZONS
from ml.train import MODEL, drop_prob, load_frame

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "reports" / "metrics.md"
RNG = np.random.default_rng(0)


def decide(mean: np.ndarray, q90: np.ndarray | None) -> tuple[np.ndarray, np.ndarray]:
    """API rule. mean, q90: (n, H) predicted ratios. Returns (wait bool, best horizon index)."""
    best = mean.argmin(axis=1)
    r = mean[np.arange(len(mean)), best]
    if q90 is None:
        return r < 1, best
    hi = q90[np.arange(len(mean)), best] - 1
    return (r < 1) & ((1 - r) > np.maximum(hi, 0)), best


def policy_stats(wait, best, actual, clusters) -> dict:
    realized = np.where(wait, actual[np.arange(len(actual)), best], 1.0)
    saving = 1 - realized
    boots = []
    uc = np.unique(clusters)
    idx = {c: np.flatnonzero(clusters == c) for c in uc}
    for _ in range(200):
        pick = np.concatenate([idx[c] for c in RNG.choice(uc, len(uc))])
        boots.append(saving[pick].mean())
    worse = wait & (realized > 1)
    return {"wait_rate": wait.mean(), "saving": saving.mean(), "lo": np.percentile(boots, 2.5),
            "hi": np.percentile(boots, 97.5),
            "saving_when_wait": saving[wait].mean() if wait.any() else 0.0,
            "worse_share_of_waits": worse.sum() / max(wait.sum(), 1), "worse_share_all": worse.mean()}


def pct(x: float, d: int = 2) -> str:
    return f"{100 * x:+.{d}f}%"


def main() -> None:
    b = joblib.load(MODEL)
    df = load_frame()
    tr, te = df[df.split == "train"], df[df.split == "test"]
    rcols = [f"ratio_{h}" for h in HORIZONS]
    te = te.dropna(subset=rcols).reset_index(drop=True)
    actual = te[rcols].to_numpy()
    clusters = (te.zone.astype(str) + "_" + te.bucket.dt.date.astype(str)).to_numpy()  # zone x day blocks

    hour_avg = {h: tr.groupby("hour")[f"ratio_{h}"].mean() for h in HORIZONS}
    ha = np.c_[[te.hour.map(hour_avg[h]).to_numpy() for h in HORIZONS]].T

    preds = {}
    for v, feats in b["features"].items():
        X = te[feats]
        ms = b["models"][v]
        preds[v] = {k: np.c_[[ms[h][k].predict(X) for h in HORIZONS]].T for k in ("mean", "q10", "q90")}
        preds[v]["p"] = np.c_[[drop_prob(ms[h], X) for h in HORIZONS]].T

    rows = {"Book now (always)": policy_stats(np.zeros(len(te), bool), np.zeros(len(te), int), actual, clusters)}
    rows["Hour-of-day average ratio"] = policy_stats(*decide(ha, None), actual, clusters)
    # extra, level-aware baseline (leakage audit): per horizon, ratio ~ a + b / level, fit on train
    lin = []
    for h in HORIZONS:
        d = tr.dropna(subset=[f"ratio_{h}"])
        c = np.polyfit(1 / d.level, d[f"ratio_{h}"], 1)
        lin.append(np.polyval(c, 1 / te.level))
    lin = np.c_[lin].T
    rows["Linear on level (1/level)"] = policy_stats(*decide(lin, None), actual, clusters)
    for v in preds:
        rows[f"When Yah? {v}"] = policy_stats(*decide(preds[v]["mean"], preds[v]["q90"]), actual, clusters)
    # "Tunggu" odds rule (served): wait 30 min when P(drop >= 10% @30) >= k x usual chance; k picked on val
    odds_wait = {}
    for v in preds:
        k = b.get("wait_k", {}).get(v)
        w = preds[v]["p"][:, 1] >= k * b["base_rate"][30] if k else np.zeros(len(te), bool)
        odds_wait[v] = (w, np.full(len(te), 1))  # horizon index 1 = +30 min
        rows[f"When Yah? {v}, odds rule (k={k})"] = policy_stats(*odds_wait[v], actual, clusters)
    oracle_best = actual.argmin(axis=1)
    rows["Oracle (perfect foresight; upper bound incl. measurement noise)"] = policy_stats(
        actual.min(axis=1) < 1, oracle_best, actual, clusters)

    surge = te.level.to_numpy() >= 1.2
    surge_rows = {}
    for name, (w, bst) in {"Book now (always)": (np.zeros(len(te), bool), np.zeros(len(te), int)),
                           "Hour-of-day average ratio": decide(ha, None),
                           "Linear on level (1/level)": decide(lin, None),
                           "When Yah? no_level": decide(preds["no_level"]["mean"], preds["no_level"]["q90"]),
                           "When Yah? with_level": decide(preds["with_level"]["mean"], preds["with_level"]["q90"]),
                           "When Yah? with_level, odds rule": odds_wait["with_level"],
                           }.items():
        surge_rows[name] = policy_stats(w[surge], bst[surge], actual[surge], clusters[surge])

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                            cwd=ROOT).stdout.strip()
    L = [f"# Metrics — When Yah? `{b['version']}`", "",
         f"Generated by `python -m ml.evaluate` on {date.today().isoformat()} (code at commit `{commit}`).",
         "Data: NYC TLC High Volume FHV trips (Uber + Lyft), Aug 2024. Unit = one pickup zone x 15-min window",
         "(>= 8 trips); price index = fare / expected fare for distance + duration (fit on train days).",
         "Split by day: **train Aug 1–21**, **val Aug 22–25** (threshold tuning), **test Aug 26–31** (below).",
         f"Test windows with all four horizons observed: **{len(te):,}** across {te.zone.nunique()} zones.",
         "Served models use no zone IDs. Intervals: 95% bootstrap over zone x day blocks (200 resamples).",
         "**Noise control:** each window's trips are split at random into halves A and B. The level the model",
         "sees comes from half A; every outcome (ratio, drop, saving) is measured on half B, so sampling noise in",
         "the current window cannot masquerade as a predictable price drop.", "",
         "## 1. Policy savings (test)",
         "Saving = 1 − (price paid ÷ price now), averaged over all test windows. Decision rule = the API's:",
         "wait for the horizon with the lowest predicted price, only if the predicted saving exceeds the",
         "p90 downside; otherwise book now. Hour-of-day baseline waits whenever the training-period mean",
         "ratio for that hour is below 1.", "",
         "| Policy | Waits | Mean saving vs book now (95% CI) | Saving when it waits | Waits that cost more |",
         "|---|---|---|---|---|"]
    for k, s in rows.items():
        L.append(f"| {k} | {s['wait_rate']:.1%} | {pct(s['saving'])} ({pct(s['lo'])} … {pct(s['hi'])}) | "
                 f"{pct(s['saving_when_wait'])} | {s['worse_share_of_waits']:.1%} |")
    L += ["", f"### When the current price is already ≥ 20% above expected (level ≥ 1.2; {surge.sum():,} test windows, "
          f"{surge.mean():.1%})", "",
          "| Policy | Waits | Mean saving vs book now (95% CI) | Saving when it waits | Waits that cost more |",
          "|---|---|---|---|---|"]
    for k, s in surge_rows.items():
        L.append(f"| {k} | {s['wait_rate']:.1%} | {pct(s['saving'])} ({pct(s['lo'])} … {pct(s['hi'])}) | "
                 f"{pct(s['saving_when_wait'])} | {s['worse_share_of_waits']:.1%} |")

    L += ["", "## 2. P(drop ≥ 10%) at each horizon (test)",
          "drop10_h = price at +h ≤ 0.9 × price now. Threshold tuned on val (max F1).", "",
          "| Variant | Horizon | Base rate | ROC-AUC | Threshold | Precision | Recall | Brier | Brier (base rate) |",
          "|---|---|---|---|---|---|---|---|---|"]
    for v in preds:
        for j, h in enumerate(HORIZONS):
            y = (actual[:, j] <= 0.9).astype(int)
            p = preds[v]["p"][:, j]
            thr = b["threshold"][(v, h)]
            yhat = (p >= thr).astype(int)
            base = y.mean()
            L.append(f"| {v} | +{h} | {base:.1%} | {roc_auc_score(y, p):.3f} | {thr:.3f} | "
                     f"{precision_score(y, yhat, zero_division=0):.1%} | {recall_score(y, yhat):.1%} | "
                     f"{brier_score_loss(y, p):.4f} | {brier_score_loss(y, np.full(len(y), tr[f'drop10_{h}'].mean())):.4f} |")
    L += ["", "Calibration, with_level +30 min (test, predicted-probability deciles):", "",
          "| Mean predicted | Observed rate | Windows |", "|---|---|---|"]
    p, y = preds["with_level"]["p"][:, 1], (actual[:, 1] <= 0.9).astype(int)
    for g in pd.DataFrame({"p": p, "y": y}).groupby(pd.qcut(p, 10, duplicates="drop"), observed=True):
        L.append(f"| {g[1].p.mean():.3f} | {g[1].y.mean():.3f} | {len(g[1]):,} |")

    L += ["", "## 3. Forecast error: MAE of ratio (test)", "",
          "| Horizon | Persistence (ratio = 1) | Hour-of-day avg | no_level | with_level | with_level vs persistence | "
          "p10–p90 band coverage (with_level) |", "|---|---|---|---|---|---|---|"]
    for j, h in enumerate(HORIZONS):
        a = actual[:, j]
        mp, mh = np.abs(a - 1).mean(), np.abs(a - ha[:, j]).mean()
        mn, mw = np.abs(a - preds["no_level"]["mean"][:, j]).mean(), np.abs(a - preds["with_level"]["mean"][:, j]).mean()
        cov = ((a >= preds["with_level"]["q10"][:, j]) & (a <= preds["with_level"]["q90"][:, j])).mean()
        L.append(f"| +{h} | {mp:.4f} | {mh:.4f} | {mn:.4f} | {mw:.4f} | {(mw - mp) / mp:+.1%} | {cov:.1%} |")

    wl, nl, ho = rows["When Yah? with_level"], rows["When Yah? no_level"], rows["Hour-of-day average ratio"]
    sw, sh = surge_rows["When Yah? with_level"], surge_rows["Hour-of-day average ratio"]
    beats = {k: rows[k]["lo"] > ho["hi"] for k in ("When Yah? with_level", "When Yah? no_level")}
    verdict = ("**When Yah? beats both baselines on held-out data.**" if any(beats.values()) else
               "**When Yah? does NOT beat the hour-of-day baseline on held-out data.** It beats \"book now\" "
               "only marginally, because it almost always advises booking now.")
    mae30 = (np.abs(actual[:, 1] - preds["with_level"]["mean"][:, 1]).mean() / np.abs(actual[:, 1] - 1).mean() - 1)
    L += ["", "## Reading (plain)", f"- {verdict}",
          f"- with_level: mean saving {pct(wl['saving'])} (hour-of-day baseline {pct(ho['saving'])}); it waits "
          f"{wl['wait_rate']:.1%} of the time, saving {pct(wl['saving_when_wait'])} when it does, but "
          f"{wl['worse_share_of_waits']:.1%} of its waits cost more. When the price is ≥ 20% high: "
          f"{pct(sw['saving'])} vs {pct(sh['saving'])} for the baseline.",
          f"- no_level waits {nl['wait_rate']:.1%} of the time: without the current level, nothing predicts a drop "
          "large enough to beat the risk.",
          f"- Forecast error at +30 min is {mae30:+.1%} vs persistence and P(drop) AUC is "
          f"{roc_auc_score((actual[:, 1] <= 0.9).astype(int), preds['with_level']['p'][:, 1]):.2f}: "
          "15-minute price changes in this data are mostly unpredictable from time, rain and the current level.",
          "- An earlier version of this report (commit 172d4a1) showed larger savings; the leakage audit found",
          "  that most of it was sampling noise (the same noisy window average was both input and outcome).",
          "  Those numbers are withdrawn. The p10–p90 band (≈ 80% coverage) is still an honest range.",
          "- All outcomes are window averages of ≥ 4 trips, not one rider re-quoting the same trip; a single",
          "  rider's band and drop chances may differ (likely a narrower band).",
          "- Patterns are learned in New York (Aug 2024) and applied to the user's local clock in Klang Valley.",
          "  They are not Malaysian data; typed quotes would become Malaysian training data (roadmap)."]
    odr, ho_ = rows[f"When Yah? with_level, odds rule (k={b['wait_k']['with_level']})"], rows["Hour-of-day average ratio"]
    validated = odr["lo"] > ho_["hi"] and odr["lo"] > 0
    L += [f"- **\"Tunggu\" odds rule** (wait 30 min when the drop chance ≥ {b['wait_k']['with_level']}× usual; k picked on val): "
          f"saving {pct(odr['saving'])} vs hour-of-day {pct(ho_['saving'])} → "
          + ("**beats both baselines; the app may advise waiting.**" if validated else
             "**does not beat the hour-of-day baseline; the app always says book now and shows the odds as information.**")]
    calib_rows = [{"mean_predicted": round(float(g[1].p.mean()), 4), "observed": round(float(g[1].y.mean()), 4),
                   "windows": int(len(g[1]))}
                  for g in pd.DataFrame({"p": p, "y": y}).groupby(pd.qcut(p, 10, duplicates="drop"), observed=True)]
    (ROOT / "reports" / "metrics.json").write_text(json.dumps({
        "source": "reports/metrics.md", "test_days": "2024-08-26..2024-08-31", "test_windows": int(len(te)),
        "policies": [{"name": k, "wait_rate": round(float(v["wait_rate"]), 4), "saving": round(float(v["saving"]), 5),
                      "saving_ci": [round(float(v["lo"]), 5), round(float(v["hi"]), 5)],
                      "waits_cost_more": round(float(v["worse_share_of_waits"]), 4)} for k, v in rows.items()],
        "auc_drop10_30": {v: round(float(roc_auc_score((actual[:, 1] <= 0.9).astype(int), preds[v]["p"][:, 1])), 3)
                          for v in preds},
        "calibration_with_level_30": calib_rows}, indent=1), encoding="utf-8")
    (ROOT / "reports" / "decision.json").write_text(json.dumps(
        {"validated": bool(validated), "rule": "wait 30 min if P(drop>=10% @30) >= k x usual",
         "k": b["wait_k"]["with_level"], "test_saving": round(float(odr["saving"]), 5),
         "hour_of_day_saving": round(float(ho_["saving"]), 5)}, indent=1), encoding="utf-8")
    REPORT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
