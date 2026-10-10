"""Model v2: the price line (expected change at +15/30/45/60 min, with a p10-p90 band) from "normal for this time"
plus "how far off normal you are now". Shared by ml/experiment_v2.py (training/evaluation) and api/forecast.py.

Two parts, in plain words:
  1. normal(hour, weekend): the usual price for this time of week, as a share of the PLACE's usual price
     (window idx / that zone's median idx on train days). Zone is used only for this scaling, never as a feature
     (rule 3). In Malaysia the place's usual price is the usual price the user types.
  2. rel_level = price now / the place's usual price; excess = rel_level - normal(now). One LightGBM per horizon
     learns how the price moves from (time, rain, events, normal now, normal at t+h, rel_level, excess).
Targets are v1's: ratio_h = idx_b(t+h) / idx_b(t) on trip-half B (split-half noise control). Every feature uses only
information available at t (normal(t+h) depends only on the clock).
Reasons: LightGBM SHAP contributions (pred_contrib) of the +30 model, summed per group -> words. They explain the
MODEL's prediction, not a proven cause; traffic is never a reason (reports/traffic_experiment.md).
"""
import numpy as np
import pandas as pd

from ml.features import BASE, EVENT, HORIZONS

TIME = ["hour", "minute", "dow", "weekend", "normal_now", "normal_h", "normal_change"]
V2_NO_LEVEL = TIME + ["rain"] + EVENT
V2_WITH_LEVEL = V2_NO_LEVEL + ["rel_level", "excess"]
VARIANTS = {"no_level": V2_NO_LEVEL, "with_level": V2_WITH_LEVEL}
GROUPS = {"time": TIME, "rain": ["rain"], "event": EVENT, "level": ["rel_level", "excess"]}
REL_RANGE = (0.5, 2.0)


def zone_medians(train: pd.DataFrame) -> pd.Series:
    """Each zone's median price index on TRAIN days = that place's usual price."""
    return train.groupby("zone").idx.median()


def normal_table(train: pd.DataFrame, zmed: pd.Series) -> pd.Series:
    """Mean of idx / zone median by (weekend, hour) on TRAIN days: the usual price for this time of week."""
    rel = train.idx / train.zone.map(zmed)
    return rel.groupby([train.weekend, train.hour]).mean()


def _normal(table: pd.Series, weekend, hour) -> np.ndarray:
    keys = pd.MultiIndex.from_arrays([np.asarray(weekend, int), np.asarray(hour, int)])
    return table.reindex(keys).fillna(1.0).to_numpy()


def add_v2(df: pd.DataFrame, h: int, table: pd.Series, zmed: pd.Series) -> pd.DataFrame:
    """Columns for the +h model. df has v1's frame columns (bucket, hour, ..., idx_a, zone)."""
    out = df.copy()
    later = out.bucket + pd.Timedelta(minutes=h)
    out["normal_now"] = _normal(table, out.weekend, out.hour)
    out["normal_h"] = _normal(table, (later.dt.dayofweek >= 5).astype(int), later.dt.hour)
    out["normal_change"] = out.normal_h - out.normal_now
    med = out.zone.map(zmed)
    out["rel_level"] = np.clip(out.idx_a / med.fillna(out.idx_a.median()), *REL_RANGE)
    out["excess"] = out.rel_level - out.normal_now
    return out


def serve_rows(row: pd.DataFrame, local_dt, table: pd.Series, rel_level: float | None) -> dict[int, pd.DataFrame]:
    """row = ml.features.serve_row(...) (one row); -> {h: feature row for the +h model}."""
    out = {}
    ts = pd.Timestamp(local_dt.replace(tzinfo=None))
    for h in HORIZONS:
        r = row.copy()
        later = ts + pd.Timedelta(minutes=h)
        r["normal_now"] = _normal(table, r.weekend, r.hour)
        r["normal_h"] = _normal(table, [int(later.dayofweek >= 5)], [later.hour])
        r["normal_change"] = r.normal_h - r.normal_now
        if rel_level is not None:
            r["rel_level"] = float(np.clip(rel_level, *REL_RANGE))
            r["excess"] = r.rel_level - r.normal_now
        out[h] = r
    return out


def contributions(model, X: pd.DataFrame) -> pd.DataFrame:
    """SHAP contribution per feature group (ratio units) for each row of X."""
    c = pd.DataFrame(model.predict(X, pred_contrib=True)[:, :-1], columns=list(X.columns), index=X.index)
    return pd.DataFrame({g: c[[f for f in fs if f in c]].sum(axis=1) for g, fs in GROUPS.items() if
                         any(f in c for f in fs)})


WORDS = {("time", 1): "prices usually rise at this time of day",
         ("time", -1): "prices usually ease at this time of day",
         ("level", -1): "your price is above your usual, and high prices usually fall back",
         ("level", 1): "your price is below your usual, and low prices usually creep back up",
         ("rain", 1): "rain", ("rain", -1): "rain",
         ("event", 1): "event timing nearby", ("event", -1): "event timing nearby"}
MIN_CONTRIB = 0.003  # a group must move the prediction by >= 0.3 percentage points to be named


def reason_words(contrib: pd.Series) -> list[str]:
    """Top 1-2 groups by absolute contribution -> phrases (largest first)."""
    top = contrib.abs().sort_values(ascending=False)
    return [WORDS[(g, 1 if contrib[g] > 0 else -1)] for g in top.index[:2] if top[g] >= MIN_CONTRIB]
