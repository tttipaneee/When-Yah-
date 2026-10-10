"""Experiment: model v2 (normal-for-this-time + how far off normal now) vs the served v1 price line.
-> ml/models/lgbm_v2.joblib, reports/metrics_v2.md, reports/v2_verdict.json

Train Aug 1-21, choose on val Aug 22-25, score on test Aug 26-31 AND on September 2024 (never seen; frozen August
fits: expected fare, zone medians, normal table, models). Same windows, targets and split-half noise control as
reports/metrics.md. Features: ml/model_v2.py (no zone IDs; zone only scales the level).

Rule (fixed in this file and committed BEFORE the first run):
  The v2 line replaces the v1 line (pct_change, pct_low, pct_high at each horizon) for a variant iff, at +30 min,
  v2's MAE of the ratio is lower than BOTH v1's and persistence's (ratio = 1), with the paired 95% CI of the
  difference (cluster bootstrap over zone x day, 300 resamples) entirely below 0, on test days AND on September.
  The "Wait / Book now" decision is NOT changed by this experiment (it keeps v1's validated rule).
  The mean-model objective (l2 or l1) is chosen on VAL MAE (with_level, +30) before looking at test or September.
Also reported (no verdict): MAE at every horizon, p10-p90 band coverage, ablation by feature group, and how big
predicted moves (|pred| >= 5%) turned out.
Usage: python -m ml.experiment_v2 [data/raw/fhvhv_tripdata_2024-09.parquet]
"""
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd

from ml import model_v2 as V
from ml.features import HORIZONS
from ml.train import MODEL as V1_MODEL, PARAMS, load_frame, mean_ratios

ROOT = Path(__file__).resolve().parent.parent
PROC = ROOT / "data" / "processed"
OUT_MODEL = ROOT / "ml" / "models" / "lgbm_v2.joblib"
REPORT = ROOT / "reports" / "metrics_v2.md"
VERDICT = ROOT / "reports" / "v2_verdict.json"
SEP_CACHE = PROC / "frame_sep.parquet"


def sep_frame(path: Path) -> pd.DataFrame:
    if SEP_CACHE.exists():
        return pd.read_parquet(SEP_CACHE)
    from ml import holdout_sep as H  # monkeypatches ml.features loaders: only after the August frame is loaded
    H.fetch_weather()
    H.fetch_events()
    z, _ = H.sep_windows(path)
    df = H.sep_frame(z)
    df.to_parquet(SEP_CACHE, index=False)
    return df


def paired(err_a: np.ndarray, err_b: np.ndarray, clusters: np.ndarray, n: int = 300) -> tuple[float, float, float]:
    """Mean of (err_a - err_b) and its 95% cluster-bootstrap CI."""
    d = pd.DataFrame({"d": err_a - err_b, "c": clusters}).groupby("c").d.agg(["sum", "count"])
    s, k = d["sum"].to_numpy(), d["count"].to_numpy()
    rng = np.random.default_rng(0)
    boots = []
    for _ in range(n):
        i = rng.integers(0, len(s), len(s))
        boots.append(s[i].sum() / k[i].sum())
    return float(s.sum() / k.sum()), float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))


def fit_v2(tr: pd.DataFrame, table, zmed, objective: str) -> dict:
    models = {}
    for name, feats in V.VARIANTS.items():
        models[name] = {}
        for h in HORIZONS:
            d = V.add_v2(tr[tr[f"ratio_{h}"].notna()], h, table, zmed)
            X, y = d[feats], d[f"ratio_{h}"]
            models[name][h] = {"mean": lgb.LGBMRegressor(objective=objective, **PARAMS).fit(X, y),
                               "q10": lgb.LGBMRegressor(objective="quantile", alpha=0.1, **PARAMS).fit(X, y),
                               "q90": lgb.LGBMRegressor(objective="quantile", alpha=0.9, **PARAMS).fit(X, y)}
            print(f"  v2 {name} +{h}: n={len(d):,}")
    return models


def score(df: pd.DataFrame, v1: dict, models: dict, table, zmed, label: str) -> dict:
    """MAE per variant/horizon for persistence, v1, v2; paired diffs at +30; coverage; big moves."""
    df = df.dropna(subset=[f"ratio_{h}" for h in HORIZONS]).reset_index(drop=True)
    clusters = (df.zone.astype(str) + "_" + df.bucket.dt.date.astype(str)).to_numpy()
    res = {"windows": int(len(df)), "mae": {}, "diff30": {}, "coverage": {}, "big": {}}
    for name in V.VARIANTS:
        p1 = mean_ratios(v1, name, df[v1["features"][name]])
        for i, h in enumerate(HORIZONS):
            y = df[f"ratio_{h}"].to_numpy()
            X = V.add_v2(df, h, table, zmed)[V.VARIANTS[name]]
            m = models[name][h]
            p2, lo, hi = m["mean"].predict(X), m["q10"].predict(X), m["q90"].predict(X)
            e0, e1, e2 = np.abs(y - 1), np.abs(y - p1[:, i]), np.abs(y - p2)
            res["mae"][(name, h)] = (e0.mean(), e1.mean(), e2.mean())
            res["coverage"][(name, h)] = float(((y >= np.minimum(lo, p2)) & (y <= np.maximum(hi, p2))).mean())
            if h == 30:
                res["diff30"][name] = {"vs_v1": paired(e2, e1, clusters), "vs_persistence": paired(e2, e0, clusters)}
                big = np.abs(p2 - 1) >= 0.05
                res["big"][name] = {"n": int(big.sum()), "share": float(big.mean()),
                                    "pred_mean": float((p2[big] - 1).mean()) if big.any() else None,
                                    "actual_mean": float((y[big] - 1).mean()) if big.any() else None,
                                    "direction_right": float((np.sign(p2[big] - 1) == np.sign(y[big] - 1)).mean())
                                    if big.any() else None}
    print(f"scored {label}: {len(df):,} windows")
    return res


def passes(r: dict, name: str) -> bool:
    d = r["diff30"][name]
    return d["vs_v1"][2] < 0 and d["vs_persistence"][2] < 0


def main() -> None:
    sep_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "raw" / "fhvhv_tripdata_2024-09.parquet"
    aug = load_frame()
    tr, va, te = (aug[aug.split == s] for s in ("train", "val", "test"))
    v1 = joblib.load(V1_MODEL)
    zmed = V.zone_medians(tr)
    table = V.normal_table(tr, zmed)

    # objective chosen on VAL (with_level, +30) before anything is scored on test / September
    d = V.add_v2(tr[tr.ratio_30.notna()], 30, table, zmed)
    dv = V.add_v2(va[va.ratio_30.notna()], 30, table, zmed)
    val_mae = {o: float(np.abs(dv.ratio_30 - lgb.LGBMRegressor(objective=o, **PARAMS).fit(
        d[V.V2_WITH_LEVEL], d.ratio_30).predict(dv[V.V2_WITH_LEVEL])).mean()) for o in ("l2", "l1")}
    objective = min(val_mae, key=val_mae.get)
    print(f"val MAE @30 with_level: {val_mae} -> objective {objective}")

    models = fit_v2(tr, table, zmed, objective)
    r_test = score(te, v1, models, table, zmed, "test Aug 26-31")
    sep = sep_frame(sep_path)
    r_sep = score(sep, v1, models, table, zmed, "September 2024")

    # ablation (test, with_level +30): drop one group, refit
    abl = {}
    dt = V.add_v2(te[te.ratio_30.notna()], 30, table, zmed)
    for g, fs in V.GROUPS.items():
        keep = [f for f in V.V2_WITH_LEVEL if f not in fs]
        m = lgb.LGBMRegressor(objective=objective, **PARAMS).fit(d[keep], d.ratio_30)
        abl[g] = float(np.abs(dt.ratio_30 - m.predict(dt[keep])).mean())
    abl["(none dropped)"] = r_test["mae"][("with_level", 30)][2]

    verdict = {name: bool(passes(r_test, name) and passes(r_sep, name)) for name in V.VARIANTS}
    bundle = {"version": "lgbm_v2", "horizons": HORIZONS, "features": V.VARIANTS, "models": models,
              "normal_table": table, "objective": objective, "verdict": verdict,
              "trained_on": "NYC HVFHV zone x 15-min windows, Aug 1-21 2024"}
    joblib.dump(bundle, OUT_MODEL, compress=3)

    def mae_rows(r):
        rows = []
        for name in V.VARIANTS:
            for h in HORIZONS:
                p, a, b = r["mae"][(name, h)]
                rows.append(f"| {name} | +{h} | {p:.4f} | {a:.4f} | {b:.4f} | {(b / a - 1):+.1%} | {r['coverage'][(name, h)]:.1%} |")
        return rows

    def diff_lines(r):
        out = []
        for name in V.VARIANTS:
            a, b = r["diff30"][name]["vs_v1"], r["diff30"][name]["vs_persistence"]
            out.append(f"- {name}: v2 − v1 {a[0]:+.5f} (95% CI {a[1]:+.5f} … {a[2]:+.5f}); "
                       f"v2 − persistence {b[0]:+.5f} ({b[1]:+.5f} … {b[2]:+.5f}) → {'passes' if passes(r, name) else 'fails'}")
        return out

    def big_lines(r):
        out = []
        for name, s in r["big"].items():
            if s["n"]:
                out.append(f"- {name}: {s['n']:,} windows ({s['share']:.1%}) predicted to move ≥ 5%; predicted "
                           f"{s['pred_mean']:+.1%} on average, actual {s['actual_mean']:+.1%}; direction right "
                           f"{s['direction_right']:.0%}")
            else:
                out.append(f"- {name}: never predicts a move ≥ 5%")
        return out

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    head = ["| Variant | Horizon | MAE persistence | MAE v1 | MAE v2 | v2 vs v1 | v2 p10–p90 coverage |",
            "|---|---|---|---|---|---|---|"]
    L = ["# Model v2 — price line from 'normal for this time' + 'how far off normal now'", "",
         f"Generated by `python -m ml.experiment_v2` on {date.today().isoformat()} (code at commit `{commit}`; rule fixed "
         "in the code before the first run). Data: NYC TLC HVFHV, train Aug 1–21 2024, val Aug 22–25, test Aug 26–31, "
         "and September 2024 (never seen, all fits frozen from August). Same windows, targets and split-half noise "
         "control as `reports/metrics.md`. No zone IDs as features; zone only scales the level (place's usual price = "
         "zone median on train days).",
         f"Mean-model objective chosen on val: **{objective}** (val MAE @30: " +
         ", ".join(f"{k} {v:.4f}" for k, v in val_mae.items()) + ").", "",
         "## Verdict (rule in the code)",
         *[f"- **{n}: {'v2 REPLACES the v1 line' if ok else 'v2 does NOT beat v1 — keep v1'}**" for n, ok in verdict.items()],
         "- The Wait / Book now decision is unchanged (v1's validated rule).", "",
         f"## Test days Aug 26–31 ({r_test['windows']:,} windows)", *diff_lines(r_test), "", *head, *mae_rows(r_test), "",
         f"## September 2024 ({r_sep['windows']:,} windows)", *diff_lines(r_sep), "", *head, *mae_rows(r_sep), "",
         "## Big predicted moves (+30 min)", "Test days:", *big_lines(r_test), "September:", *big_lines(r_sep), "",
         "## Ablation (test, with_level +30, MAE when one group is left out)", "",
         "| Left out | MAE |", "|---|---|", *[f"| {g} | {m:.4f} |" for g, m in abl.items()], "",
         "## Normal for this time (share of the place's usual price, train days)", "",
         "| Hour | Weekday | Weekend |", "|---|---|---|",
         *[f"| {h:02d}:00 | {table.get((0, h), float('nan')):.3f} | {table.get((1, h), float('nan')):.3f} |" for h in range(24)],
         "", "## Reading (plain)",
         "- MAE includes trip-sampling noise that no model can remove (the oracle bound in `reports/metrics.md`).",
         "- 'Reasons' shown in the app are the model's SHAP contributions grouped into time / your price vs usual / rain /",
         "  event: why the MODEL predicts the move, not a proven cause. Traffic is never named (tested: no price effect).",
         "- Still New York data; in Malaysia the place's usual price is the usual price the user types."]
    REPORT.write_text("\n".join(L) + "\n", encoding="utf-8")
    VERDICT.write_text(json.dumps({"source": "reports/metrics_v2.md", "objective": objective, "verdict": verdict,
                                   "test": {n: r_test["diff30"][n] for n in V.VARIANTS},
                                   "september": {n: r_sep["diff30"][n] for n in V.VARIANTS},
                                   "big_moves": {"test": r_test["big"], "september": r_sep["big"]},
                                   "ablation_test_mae30": abl}, indent=1), encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
