"""Model v2: the price line (expected change at +15/30/45/60 min, with a p10-p90 band) from "normal for this time"
plus "how far off normal you are now". Shared by ml/experiment_v2.py (training/evaluation) and api/forecast.py.

Two parts, in plain words:
  1. normal(hour, weekend): the usual price for this time of week, as a share of the PLACE's usual price
     (window idx / that zone's median idx on train days). Zone is used only for this scaling, never as a feature
     (rule 3). In Malaysia the place's usual price is the usual price the user types.
  2. rel_level = price now / the place's usual price; excess = rel_level - normal(now). One LightGBM per horizon
     learns how the price moves from (time, rain, events, normal now, normal at t+h, rel_level, excess).
Event features are trained but always zero when serving (Malaysian events are never fed to the model; the ablation in
reports/metrics_v2.md shows they add nothing, and zeroing them changes MAE by < 0.00001).
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
    out["rel_level"] = np.clip(out.idx_a / med.fillna(float(zmed.median())), *REL_RANGE)  # unseen zone: train constant
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


def fit_median_cal(pred: np.ndarray, y: np.ndarray, step: float = 0.01, min_n: int = 30):
    """Isotonic map predicted -> observed MEDIAN ratio, on fixed 1-point bins of the prediction (merged until each has
    >= min_n windows, weighted by size), so it keeps the l1 model's 'typical outcome' meaning (a plain isotonic fit
    estimates the mean and shifted every forecast ~+0.5 points; quantile bins pooled all rare big moves into one bin
    and capped drops at ~-4%: leakage audit / rerun, 11 Oct)."""
    from sklearn.isotonic import IsotonicRegression
    d = pd.DataFrame({"p": pred, "y": y}).sort_values("p")
    d["b"] = np.floor(d.p / step)
    xs, ys, ws, cur = [], [], [], []
    for _, g in d.groupby("b", sort=True):
        cur.append(g)
        if sum(len(c) for c in cur) >= min_n:
            m = pd.concat(cur)
            xs.append(m.p.median()); ys.append(m.y.median()); ws.append(len(m)); cur = []
    if cur and xs:  # leftover tail merges into the last bin
        m = pd.concat(cur + [d[d.p >= xs[-1]]])
        xs[-1], ys[-1], ws[-1] = m.p.median(), m.y.median(), len(m)
    return IsotonicRegression(out_of_bounds="clip").fit(xs, ys, sample_weight=ws)


def predict_line(m: dict, X: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(typical, p10, p90) ratios. If m has "cal" (isotonic, fit on VAL days: predicted -> observed median), the value is
    mapped through it and the band shifted by the same amount (added 11 Oct after September showed the raw line
    overstating big moves ~1.5x, reports/metrics_v2.md)."""
    mean, lo, hi = m["mean"].predict(X), m["q10"].predict(X), m["q90"].predict(X)
    if "cal" in m:
        c = m["cal"].predict(mean)
        lo, hi, mean = lo + (c - mean), hi + (c - mean), c
    return mean, np.minimum(lo, mean), np.maximum(hi, mean)


def contributions(model, X: pd.DataFrame) -> pd.DataFrame:
    """SHAP contribution per feature group (ratio units) for each row of X."""
    c = pd.DataFrame(model.predict(X, pred_contrib=True)[:, :-1], columns=list(X.columns), index=X.index)
    return pd.DataFrame({g: c[[f for f in fs if f in c]].sum(axis=1) for g, fs in GROUPS.items() if
                         any(f in c for f in fs)})


MIN_CONTRIB = 0.003  # a group must move the prediction by >= 0.3 percentage points to be named


def reason_words(contrib: pd.Series, row: pd.Series, shown_pct: float | None = None) -> list[str]:
    """Top 1-2 groups by absolute contribution -> phrases (largest first). A group is named only when its words
    are true for this row (rain only if raining; "above/below normal" only if the level pushes the same way) and,
    when the shown change is clearly up or down (|pct| >= 0.5%), only if it pushes the same way as the shown number."""
    out = []
    for g in contrib.abs().sort_values(ascending=False).index:
        c = contrib[g]
        if abs(c) < MIN_CONTRIB or len(out) == 2:
            break
        if shown_pct is not None and abs(shown_pct) >= 0.005 and np.sign(c) != np.sign(shown_pct):
            continue
        if g == "time":
            out.append("prices usually rise at this time of day" if c > 0 else "prices usually ease at this time of day")
        elif g == "level" and "excess" in row:
            if c < 0 and row.excess > 0:
                out.append("your price is above normal for this time, and high prices usually fall back")
            elif c > 0 and row.excess < 0:
                out.append("your price is below normal for this time, and low prices usually creep back up")
        elif g == "rain" and row.rain == 1:
            out.append("it's raining")
        elif g == "event" and row.event_nearby == 1:
            out.append("event timing nearby")
    return out
