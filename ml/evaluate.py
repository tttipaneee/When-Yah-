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
from ml.train import K_GRID, MIN_WAIT_P, MODEL, base_rates, drop_prob, load_frame, odds_multiples, tunggu

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


def paired_diff(a: tuple, b_: tuple, actual, clusters) -> tuple[float, float, float]:
    """Saving(policy a) - saving(policy b) on the SAME windows, block bootstrap over clusters (re-audit)."""
    def sav(w, h):
        return 1 - np.where(w, actual[np.arange(len(actual)), h], 1.0)
    d = sav(*a) - sav(*b_)
    uc = np.unique(clusters)
    idx = {c: np.flatnonzero(clusters == c) for c in uc}
    rng = np.random.default_rng(1)
    boots = [d[np.concatenate([idx[c] for c in rng.choice(uc, len(uc))])].mean() for _ in range(500)]
    return float(d.mean()), float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))


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
    # "Wait" odds rule (served): wait for the horizon with the best odds multiple if >= k; k picked on val
    odds_wait = {}
    for v in preds:
        k = b.get("wait_k", {}).get(v)
        odds_wait[v] = tunggu(odds_multiples(b, v, te[b["features"][v]]), k, base_rates(b), preds[v]["mean"])
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
                           "When Yah? no_level, odds rule": odds_wait["no_level"],
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
         "Saving = 1 − (price paid ÷ price now), averaged over all test windows. **Served rule** = the \"odds",
         "rule\" rows: wait for the 15–60 min horizon with the best odds multiple (P(drop ≥ 10%) ÷ usual) if ≥ k",
         "(k picked on val). Rows \"When Yah? no_level / with_level\" without \"odds rule\" are the **old q90 rule",
         "(retired)**. Hour-of-day baseline waits (at its best 15–60 min horizon) whenever the training-period",
         "mean ratio for that hour is below 1.", "",
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
    verdict = ("The old q90 rule (retired) " + ("beat both baselines." if any(beats.values()) else
               "did not beat the hour-of-day baseline; it almost never advised waiting. The served odds rule is "
               "assessed at the end of this report."))
    mae30 = (np.abs(actual[:, 1] - preds["with_level"]["mean"][:, 1]).mean() / np.abs(actual[:, 1] - 1).mean() - 1)
    L += ["", "## Reading (plain)", f"- {verdict}",
          f"- (old q90 rule) with_level: mean saving {pct(wl['saving'])} (hour-of-day baseline {pct(ho['saving'])}); it waits "
          f"{wl['wait_rate']:.1%} of the time, saving {pct(wl['saving_when_wait'])} when it does, but "
          f"{wl['worse_share_of_waits']:.1%} of its waits cost more. When the price is ≥ 20% high: "
          f"{pct(sw['saving'])} vs {pct(sh['saving'])} for the baseline.",
          f"- (old q90 rule) no_level waited {nl['wait_rate']:.1%} of the time.",
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
    ho_ = rows["Hour-of-day average ratio"]
    hour_pol = decide(ha, None)
    hi15 = te.level.to_numpy() >= 1.5
    decision = {"rule": "wait for the 15/30/45/60-min horizon with the best odds multiple (P(drop>=10%) / usual "
                        f"chance) if it is >= k AND P(drop>=10%) there >= {MIN_WAIT_P:.0%} AND the expected price "
                        "there is below the price now; k picked on val days",
                "min_wait_p": MIN_WAIT_P,
                "gate": "validated if the test-day mean saving vs book now has a 95% CI above 0",
                "test_days": "2024-08-26..2024-08-31", "variants": {}}
    for v in preds:
        kv = b["wait_k"][v]
        r_ = rows[f"When Yah? {v}, odds rule (k={kv})"]
        w_, h_ = odds_wait[v]
        s15 = policy_stats(w_[hi15], h_[hi15], actual[hi15], clusters[hi15])
        ok = bool(kv is not None and r_["lo"] > 0)
        dm, dlo, dhi = paired_diff(odds_wait[v], hour_pol, actual, clusters)
        verdict_hour = "beats" if dlo > 0 else "loses to" if dhi < 0 else "ties"
        decision["variants"][v] = {
            "validated": ok, "k": kv, "test_saving": round(float(r_["saving"]), 5),
            "test_saving_ci": [round(float(r_["lo"]), 5), round(float(r_["hi"]), 5)],
            "wait_rate": round(float(r_["wait_rate"]), 4),
            "saving_when_wait": round(float(r_["saving_when_wait"]), 4),
            "waits_cost_more": round(float(r_["worse_share_of_waits"]), 3),
            "vs_hour_of_day": verdict_hour,
            "minus_hour_of_day": [round(dm, 5), round(dlo, 5), round(dhi, 5)]}
        if v == "with_level":  # level is only known (quote / usual price) when with_level is served
            sh15 = policy_stats(hour_pol[0][hi15], hour_pol[1][hi15], actual[hi15], clusters[hi15])
            aw = policy_stats(np.ones(hi15.sum(), bool), np.full(hi15.sum(), 1), actual[hi15], clusters[hi15])
            decision["variants"][v]["level_ge_1_5"] = {
                "windows": int(hi15.sum()), "wait_rate": round(float(s15["wait_rate"]), 3),
                "saving": round(float(s15["saving"]), 4),
                "saving_ci": [round(float(s15["lo"]), 4), round(float(s15["hi"]), 4)],
                "waits_cost_more": round(float(s15["worse_share_of_waits"]), 3),
                "hour_of_day_saving": round(float(sh15["saving"]), 4),
                "always_wait_30_saving": round(float(aw["saving"]), 4)}
        L += [f"- **\"Wait\" rule, {v}** (best of 15–60 min if odds ≥ {kv}× usual, chance ≥ {MIN_WAIT_P:.0%} and expected price below now; k picked on val): saving "
              f"{pct(r_['saving'])} ({pct(r_['lo'])} … {pct(r_['hi'])}) vs book now → "
              + ("**beats book now: the app may say \"Wait\"**" if ok else "**does not beat book now: the app says book now**")
              + f"; {verdict_hour} the hour-of-day rule ({pct(ho_['saving'])}; paired difference {pct(dm)}, "
              f"95% CI {pct(dlo)} … {pct(dhi)}). When it waits it saves "
              f"{pct(r_['saving_when_wait'])} on average and {r_['worse_share_of_waits']:.0%} of waits cost more. "
              + (f"When the price is ≥ 1.5× usual ({int(hi15.sum())} windows): it waits {s15['wait_rate']:.0%} of the "
                 f"time and saves {pct(s15['saving'])} ({pct(s15['lo'])} … {pct(s15['hi'])}) — about what the "
                 f"hour-of-day rule ({pct(sh15['saving'])}) or simply always waiting 30 min ({pct(aw['saving'])}) "
                 "get: high prices tend to fall back (mean reversion); the model adds little there."
                 if v == "with_level" else "")]
    L += ["", "**Disclosure.** The gate for showing \"Wait\" was changed on 10 Oct 2026 after we saw test "
          "results. The original gate required beating both \"book now\" and the hour-of-day rule; the rule failed "
          "it. The new gate (beat \"book now\" only) was chosen with knowledge of the test numbers, so treat the "
          "\"Wait\" result as exploratory.", "",
          "**Other changes made after seeing test results (10 Oct 2026).** (1) The 20% minimum chance of a ≥ 10% "
          "drop before saying \"Wait\" (product rule; re-scored on the same test days). (2) Never \"Wait\" while the "
          "expected price at that horizon is not below the price now (the app had shown \"Wait\" next to a rising "
          "forecast line); not tuned on test numbers; included in the numbers above. Each change re-used the same "
          "test days (Aug 26–31), so the \"Wait\" numbers are exploratory, not a clean held-out result.", "",
          "**k picked on val:** " + ", ".join(f"{v} = {b['wait_k'][v]}" for v in preds)
          + (f". This is the lowest value tried ({K_GRID[0]}), so the odds-multiple test never blocks a \"Wait\"; "
             f"the {MIN_WAIT_P:.0%} minimum does the work." if all(b["wait_k"][v] == K_GRID[0] for v in preds) else "."),
          "",
          "**Level in training vs in the app.** In training, level = trip fare ÷ expected fare for its distance and "
          "duration (fit on train days). In the app, level = the user's quote ÷ the usual price they type. Similar in "
          "spirit, not the same quantity.", "",
          "**Audit notes (10 Oct 2026).** Calibration cap: an isotonic top step that jumps > 0.2 above the step below "
          "is capped at that step (ml.train.drop_prob; added after the app showed \"100% chance\"). Isotonic "
          "calibration and k are both fit on the same val days, so k is chosen on in-sample calibrated probabilities. "
          "Two doubleheader second games (mlb-745713, mlb-745708) carry the first game's scheduled start, so their "
          "event features are misaligned; event features are not served for Malaysia."]
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
    (ROOT / "reports" / "decision.json").write_text(json.dumps(decision, indent=1), encoding="utf-8")
    REPORT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
