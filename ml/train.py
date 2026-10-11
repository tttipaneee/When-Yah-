"""Train LightGBM models on TRAIN days only -> ml/models/lgbm_v1.joblib

Two variants: no_level (time, rain, events) and with_level (+ current level idx_a(t) from trip-half A).
Per variant and horizon h in 15/30/45/60: mean ratio (L2), p10 and p90 ratio (quantile) for the band,
and a classifier for drop10_h (ratio_h <= 0.9). The p_drop10 decision threshold is tuned on VAL (max F1).
Usage: python ml/train.py
"""
import time
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import precision_recall_curve

from ml.features import HORIZONS, NO_LEVEL, WITH_LEVEL, build_frame

ROOT = Path(__file__).resolve().parent.parent
PROC = ROOT / "data" / "processed"
MODEL = ROOT / "ml" / "models" / "lgbm_v1.joblib"
PARAMS = dict(n_estimators=300, learning_rate=0.05, num_leaves=31, min_child_samples=200,
              subsample=0.8, subsample_freq=1, colsample_bytree=0.9, verbose=-1, n_jobs=4)
VARIANTS = {"no_level": NO_LEVEL, "with_level": WITH_LEVEL}


def load_frame() -> pd.DataFrame:
    cache = PROC / "frame.parquet"
    src = PROC / "windows.parquet"
    inputs = [src, ROOT / "ml" / "features.py", ROOT / "data" / "events" / "nyc_events_2024-08.csv",
              ROOT / "data" / "weather" / "nyc_central_park_2024-08.csv"]
    if cache.exists() and cache.stat().st_mtime > max(p.stat().st_mtime for p in inputs):
        return pd.read_parquet(cache)
    df = build_frame(pd.read_parquet(src))
    df.to_parquet(cache, index=False)
    return df


def clf_for(name: str, feats: list[str]) -> lgb.LGBMClassifier:
    """with_level: smaller leaves + drop chance monotone in level (kept per reports/extreme_experiment.md)."""
    if name != "with_level":
        return lgb.LGBMClassifier(**PARAMS)
    return lgb.LGBMClassifier(**{**PARAMS, "min_child_samples": 50},
                              monotone_constraints=[1 if f == "level" else 0 for f in feats])


def drop_prob(m: dict, X) -> np.ndarray:
    """Calibrated P(drop >= 10%) — use this everywhere (evaluate, API), never m["clf"] directly."""
    p = m["clf"].predict_proba(X)[:, 1]
    if "cal" not in m:
        return p
    q = m["cal"].predict(p)
    # Audit fix (10 Oct, post hoc): an isotonic top step that jumps > 0.2 above the step below rests on a handful
    # of val windows (with_level +15 jumped 0.346 -> 1.0 and the app showed "100% chance"); cap at the step below
    y = np.unique(m["cal"].y_thresholds_)
    if len(y) > 1 and y[-1] - y[-2] > TOP_STEP_JUMP:
        q = np.minimum(q, y[-2])
    return q


TOP_STEP_JUMP = 0.2


K_GRID = (1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0)


def odds_multiples(bundle: dict, name: str, X) -> np.ndarray:
    """(n, 4): calibrated P(drop >= 10%) at +15/30/45/60 divided by the usual (train) chance at that horizon."""
    ms = bundle["models"][name]
    return np.c_[[drop_prob(ms[h], X) / bundle["base_rate"][h] for h in HORIZONS]].T


MIN_WAIT_P = 0.40  # product rule (Ravin; 20% on 10 Oct, raised to 40% on 11 Oct): never advise waiting below this chance of a >= 10% drop


def tunggu(mult: np.ndarray, k: float | None, base: np.ndarray | None = None,
           mean: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """"Wait" rule: wait for the horizon with the best odds multiple if it is >= k AND the chance of a >= 10%
    drop there is >= MIN_WAIT_P AND the expected price there is below the price now (product rule, 10 Oct:
    never say "Wait" while the expected line is rising). base = usual chance per horizon; mean = (n, 4)
    predicted ratios. -> (wait, horizon index)."""
    best = mult.argmax(axis=1)
    if k is None:
        return np.zeros(len(mult), bool), best
    m = mult[np.arange(len(mult)), best]
    wait = m >= k
    if base is not None:
        wait &= m * np.asarray(base)[best] >= MIN_WAIT_P
    if mean is not None:
        wait &= np.asarray(mean)[np.arange(len(mult)), best] < 1
    return wait, best


def mean_ratios(bundle: dict, name: str, X) -> np.ndarray:
    """(n, 4): predicted mean ratio (price at +h / price now) at +15/30/45/60."""
    ms = bundle["models"][name]
    return np.c_[[ms[h]["mean"].predict(X) for h in HORIZONS]].T


def base_rates(bundle: dict) -> np.ndarray:
    return np.array([bundle["base_rate"][h] for h in HORIZONS])


def choose_wait_k(bundle: dict, name: str, va: pd.DataFrame) -> float | None:
    """Pick k for the "Wait" rule on VAL days (highest mean saving vs book now, waiting at the chosen
    horizon); None (= never advise waiting) if no k saves money on val."""
    v = va.dropna(subset=[f"ratio_{h}" for h in HORIZONS])
    actual = v[[f"ratio_{h}" for h in HORIZONS]].to_numpy()
    mult = odds_multiples(bundle, name, v[bundle["features"][name]])
    mean = mean_ratios(bundle, name, v[bundle["features"][name]])
    best, best_saving = None, 0.0
    for k in K_GRID:
        wait, h = tunggu(mult, k, base_rates(bundle), mean)
        saving = float(np.where(wait, 1 - actual[np.arange(len(v)), h], 0.0).mean())
        print(f"  {name} k={k}: val waits {wait.mean():.2%}, mean saving {saving:+.3%}")
        if saving > best_saving:
            best, best_saving = k, saving
    print(f"  {name}: chosen k = {best}")
    return best


def main() -> None:
    df = load_frame()
    tr, va = df[df.split == "train"], df[df.split == "val"]
    bundle = {"version": "lgbm_v1", "horizons": HORIZONS, "features": VARIANTS, "models": {},
              "threshold": {}, "trained_on": "NYC HVFHV zone x 15-min windows, Aug 1-21 2024",
              # typical chance of a >= 10% drop at each horizon (train days) — the "usual" odds shown to users
              "base_rate": {h: float(tr[f"drop10_{h}"].mean()) for h in HORIZONS}}
    for name, feats in VARIANTS.items():
        bundle["models"][name] = {}
        for h in HORIZONS:
            t0 = time.time()
            d = tr[tr[f"ratio_{h}"].notna()]
            X, y = d[feats], d[f"ratio_{h}"]
            m = {"mean": lgb.LGBMRegressor(**PARAMS).fit(X, y),
                 "q10": lgb.LGBMRegressor(objective="quantile", alpha=0.1, **PARAMS).fit(X, y),
                 "q90": lgb.LGBMRegressor(objective="quantile", alpha=0.9, **PARAMS).fit(X, y),
                 "clf": clf_for(name, feats).fit(X, d[f"drop10_{h}"].astype(int))}
            bundle["models"][name][h] = m
            v = va[va[f"drop10_{h}"].notna()]
            # isotonic calibration on VAL (re-audit: raw probabilities were overconfident above ~0.55)
            m["cal"] = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(
                m["clf"].predict_proba(v[feats])[:, 1], v[f"drop10_{h}"].astype(int))
            p = drop_prob(m, v[feats])
            prec, rec, thr = precision_recall_curve(v[f"drop10_{h}"].astype(int), p)
            f1 = 2 * prec * rec / np.maximum(prec + rec, 1e-9)
            bundle["threshold"][(name, h)] = float(thr[np.argmax(f1[:-1])])
            print(f"{name:10s} +{h:2d} min: n_train={len(d):,} val_thr={bundle['threshold'][(name, h)]:.3f} "
                  f"({time.time() - t0:.0f}s)")
    bundle["wait_k"] = {name: choose_wait_k(bundle, name, va) for name in VARIANTS}
    MODEL.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, MODEL, compress=3)  # committed so the demo runs without the raw data
    print(f"saved {MODEL}")


if __name__ == "__main__":
    main()
