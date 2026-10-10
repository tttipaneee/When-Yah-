"""Side-by-side accuracy of the v1 and v2 price lines (as served) -> reports/compare_v1_v2.md / .json

Same windows, targets (ratio_h on trip-half B) and splits as reports/metrics_v2.md: test days Aug 26-31 2024 and
September 2024 (frozen August fits). No verdicts here (the rule lives in ml/experiment_v2.py); this file only
describes accuracy in plain terms:
  - MAE of the predicted change, also in RM on a RM 20 quote (MAE x 20)
  - direction: when a model predicts a move of >= 2%, how often the price moved that way
  - surges (price >= 1.5x the place's usual): predicted vs actual median change
  - size check: predicted vs actual median change by predicted bin
  - v2 direction by size of the call (>= 1/2/5/10%), and the served Wait advice (v1 rule + v2 line falling; the RM 1.50
    minimum is not applied: NYC data has no Malaysian quotes): how often the price was lower / 10%+ lower / higher
Usage: python -m ml.compare_v1_v2   (needs data/processed/frame.parquet and frame_sep.parquet from ml/experiment_v2.py)
"""
import json
import subprocess
from datetime import date
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from ml import model_v2 as V
from ml.features import HORIZONS
from ml.train import MODEL as V1_MODEL, base_rates, load_frame, mean_ratios, odds_multiples, tunggu

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "reports" / "compare_v1_v2.md"
QUOTE_RM = 20.0
BINS = [-1, -0.10, -0.05, -0.02, 0.02, 0.05, 1]


def describe(df: pd.DataFrame, v1: dict, v2: dict, zmed) -> dict:
    df = df.dropna(subset=[f"ratio_{h}" for h in HORIZONS]).reset_index(drop=True)
    out = {"windows": int(len(df))}
    ys = df[[f"ratio_{h}" for h in HORIZONS]].to_numpy()
    lines = {}
    for name in V.VARIANTS:
        p1 = mean_ratios(v1, name, df[v1["features"][name]])
        r = {"mae": {}}
        for i, h in enumerate(HORIZONS):
            X = V.add_v2(df, h, v2["normal_table"], zmed)
            p2 = V.predict_line(v2["models"][name][h], X[V.VARIANTS[name]])[0]
            lines.setdefault(name, []).append(p2)
            y = df[f"ratio_{h}"].to_numpy()
            r["mae"][h] = {"persistence": float(np.abs(y - 1).mean()), "v1": float(np.abs(y - p1[:, i]).mean()),
                           "v2": float(np.abs(y - p2).mean())}
            if h != 30:
                continue
            for tag, p in (("v1", p1[:, i]), ("v2", p2)):
                ch = p - 1
                mv = np.abs(ch) >= 0.02
                r[f"direction_{tag}"] = {"share_predicting_move": float(mv.mean()),
                                         "right": float((np.sign(ch[mv]) == np.sign(y[mv] - 1)).mean()) if mv.any() else None,
                                         "flat_share": float((np.abs(ch) < 0.01).mean())}
                t = pd.DataFrame({"p": ch, "y": y - 1})
                r[f"size_{tag}"] = [{"bin": str(k), "n": int(len(g)), "pred": float(g.p.median()), "actual": float(g.y.median())}
                                    for k, g in t.groupby(pd.cut(t.p, BINS), observed=True)]
            ch2, moved = p2 - 1, y != 1
            r["direction_v2_by_size"] = [{"min_move": t, "share": float((np.abs(ch2) >= t).mean()),
                                          "right": float((np.sign(ch2[m]) == np.sign(y[m] - 1)).mean()) if m.any() else None}
                                         for t in (0.01, 0.02, 0.05, 0.10) for m in [(np.abs(ch2) >= t) & moved]]
            surge = (X.rel_level >= 1.5).to_numpy()
            r["surge"] = {"n": int(surge.sum()), "actual_median": float(np.median(y[surge] - 1)),
                          "v1_pred_median": float(np.median(p1[surge, i] - 1)), "v2_pred_median": float(np.median(p2[surge] - 1)),
                          "mae_persistence": float(np.abs(y[surge] - 1).mean()),
                          "mae_v1": float(np.abs(y[surge] - p1[surge, i]).mean()),
                          "mae_v2": float(np.abs(y[surge] - p2[surge]).mean())}
        Xv = df[v1["features"][name]]
        wait, best = tunggu(odds_multiples(v1, name, Xv), v1["wait_k"][name], base_rates(v1), mean_ratios(v1, name, Xv))
        line = np.c_[lines[name]].T
        idx = np.arange(len(df))
        wait &= line[idx, best] < 1
        a = ys[idx, best][wait]
        r["wait"] = {"share": float(wait.mean()), "n": int(wait.sum()), "lower": float((a < 1).mean()),
                     "lower10": float((a <= 0.9).mean()), "higher": float((a > 1).mean()), "saving": float((1 - a).mean())}
        out[name] = r
    return out


def main() -> None:
    aug = load_frame()
    tr, te = aug[aug.split == "train"], aug[aug.split == "test"]
    v1, v2 = joblib.load(V1_MODEL), joblib.load(ROOT / "ml" / "models" / "lgbm_v2.joblib")
    zmed = V.zone_medians(tr)
    res = {"test": describe(te, v1, v2, zmed),
           "september": describe(pd.read_parquet(ROOT / "data" / "processed" / "frame_sep.parquet"), v1, v2, zmed)}
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    L = ["# v1 vs v2 price line — accuracy side by side", "",
         f"Generated by `python -m ml.compare_v1_v2` on {date.today().isoformat()} (code at commit `{commit}`). Same windows "
         "and targets as `reports/metrics_v2.md`; lines as served (v2 median-calibrated). NYC TLC HVFHV, test days "
         "Aug 26–31 2024 and September 2024 (never seen). Pass/fail lives in `reports/metrics_v2.md`; this file only "
         f"describes accuracy. RM figures = error on a RM {QUOTE_RM:.0f} quote.", ""]
    for setname, r in res.items():
        L += [f"## {'Test days Aug 26–31' if setname == 'test' else 'September 2024'} ({r['windows']:,} windows)", "",
              "| Variant | Horizon | Persistence MAE | v1 MAE | v2 MAE | v1 RM error | v2 RM error |", "|---|---|---|---|---|---|---|"]
        for name in V.VARIANTS:
            for h in HORIZONS:
                m = r[name]["mae"][h]
                L.append(f"| {name} | +{h} | {m['persistence']:.4f} | {m['v1']:.4f} | {m['v2']:.4f} | "
                         f"RM {m['v1'] * QUOTE_RM:.3f} | RM {m['v2'] * QUOTE_RM:.3f} |")
        L += ["", "Direction at +30 (when a model predicts a move of ≥ 2%):", ""]
        for name in V.VARIANTS:
            for tag in ("v1", "v2"):
                d = r[name][f"direction_{tag}"]
                L.append(f"- {name} {tag}: predicts a move in {d['share_predicting_move']:.1%} of windows; right direction "
                         + (f"{d['right']:.0%}" if d["right"] is not None else "–") + f"; about flat (< 1%) in {d['flat_share']:.0%}")
        L += ["", "v2 direction by size of the call (+30; moments where the price moved):", ""]
        for name in V.VARIANTS:
            L.append(f"- {name}: " + "; ".join(f"≥ {d['min_move']:.0%}: {d['share']:.1%} of moments, right "
                                              + (f"{d['right']:.0%}" if d["right"] is not None else "–")
                                              for d in r[name]["direction_v2_by_size"]))
        L += ["", "Served Wait advice (v1 rule + v2 line falling; RM 1.50 minimum not applied):", ""]
        for name in V.VARIANTS:
            w = r[name]["wait"]
            L.append(f"- {name}: says Wait in {w['share']:.1%} of moments ({w['n']:,}); after waiting the price was lower "
                     f"{w['lower']:.0%}, 10%+ lower {w['lower10']:.0%}, higher {w['higher']:.0%}; average saving {w['saving']:+.1%}")
        s = r["with_level"]["surge"]
        L += ["", f"Surges (≥ 1.5× the place's usual, with_level +30, {s['n']:,} windows): actual median {s['actual_median']:+.1%}; "
              f"v1 predicted {s['v1_pred_median']:+.1%}, v2 {s['v2_pred_median']:+.1%}; MAE persistence {s['mae_persistence']:.4f}, "
              f"v1 {s['mae_v1']:.4f}, v2 {s['mae_v2']:.4f}.", ""]
    REPORT.write_text("\n".join(L) + "\n", encoding="utf-8")
    REPORT.with_suffix(".json").write_text(json.dumps({"source": "reports/compare_v1_v2.md", "commit": commit,
                                                       "quote_rm": QUOTE_RM, **res}, indent=1), encoding="utf-8")
    print(REPORT.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
