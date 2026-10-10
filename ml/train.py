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


def main() -> None:
    df = load_frame()
    tr, va = df[df.split == "train"], df[df.split == "val"]
    bundle = {"version": "lgbm_v1", "horizons": HORIZONS, "features": VARIANTS, "models": {},
              "threshold": {}, "trained_on": "NYC HVFHV zone x 15-min windows, Aug 1-21 2024"}
    for name, feats in VARIANTS.items():
        bundle["models"][name] = {}
        for h in HORIZONS:
            t0 = time.time()
            d = tr[tr[f"ratio_{h}"].notna()]
            X, y = d[feats], d[f"ratio_{h}"]
            m = {"mean": lgb.LGBMRegressor(**PARAMS).fit(X, y),
                 "q10": lgb.LGBMRegressor(objective="quantile", alpha=0.1, **PARAMS).fit(X, y),
                 "q90": lgb.LGBMRegressor(objective="quantile", alpha=0.9, **PARAMS).fit(X, y),
                 "clf": lgb.LGBMClassifier(**PARAMS).fit(X, d[f"drop10_{h}"].astype(int))}
            bundle["models"][name][h] = m
            v = va[va[f"drop10_{h}"].notna()]
            p = m["clf"].predict_proba(v[feats])[:, 1]
            prec, rec, thr = precision_recall_curve(v[f"drop10_{h}"].astype(int), p)
            f1 = 2 * prec * rec / np.maximum(prec + rec, 1e-9)
            bundle["threshold"][(name, h)] = float(thr[np.argmax(f1[:-1])])
            print(f"{name:10s} +{h:2d} min: n_train={len(d):,} val_thr={bundle['threshold'][(name, h)]:.3f} "
                  f"({time.time() - t0:.0f}s)")
    MODEL.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, MODEL, compress=3)  # committed so the demo runs without the raw data
    print(f"saved {MODEL}")


if __name__ == "__main__":
    main()
