"""Features and targets. Shared by training (NYC windows) and serving (api/forecast.py).

Every feature uses only information available at time t:
  time:    hour, minute, dow, weekend (local clock at the pickup)
  weather: rain = last hourly report at or before t had precipitation > 0 (user toggle when serving)
  events:  event_nearby, during_event, minutes_to_start, minutes_since_end, from the SCHEDULED start
           (known in advance) and an assumed end = scheduled start + median train-game duration
  level:   idx_a(t), current price / expected price from trip-half A (with-level variant only; served as
           quote / usual price)
No zone IDs (area-agnostic). Targets use trip-half B (independent of the level's sampling noise):
ratio_h = idx_b(t+h) / idx_b(t), drop10_h = ratio_h <= 0.9. Targets whose t+h falls in the next split
are dropped. Decision time: a window [t, t+15) is summarised at its start t; horizons are start to start.
"""
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
HORIZONS = (15, 30, 45, 60)
PRE_MIN, POST_MIN = 180, 120   # event window: 3 h before start .. 2 h after end
FAR = 999.0                    # sentinel: no event in that window
BASE = ["hour", "minute", "dow", "weekend", "rain"]
EVENT = ["event_nearby", "during_event", "minutes_to_start", "minutes_since_end"]
NO_LEVEL = BASE + EVENT
WITH_LEVEL = NO_LEVEL + ["level"]
LEVEL_RANGE = (0.5, 2.0)       # serving clip, inside the training range of idx_a


def time_features(ts: pd.Series) -> pd.DataFrame:
    return pd.DataFrame({"hour": ts.dt.hour, "minute": ts.dt.minute, "dow": ts.dt.dayofweek,
                         "weekend": (ts.dt.dayofweek >= 5).astype(int)}, index=ts.index)


def event_features(t: np.ndarray, starts: np.ndarray, ends: np.ndarray) -> dict[str, np.ndarray]:
    """t, starts, ends in minutes (same clock). Uses the event nearest in time for each t."""
    n = len(t)
    out = {"event_nearby": np.zeros(n), "during_event": np.zeros(n),
           "minutes_to_start": np.full(n, FAR), "minutes_since_end": np.full(n, FAR)}
    for s, e in zip(starts, ends):
        to_start = s - t
        since_end = t - e
        pre = (to_start > 0) & (to_start <= PRE_MIN)
        during = (to_start <= 0) & (since_end < 0)
        post = (since_end >= 0) & (since_end <= POST_MIN)
        out["event_nearby"][pre | during | post] = 1
        out["during_event"][during] = 1
        out["minutes_to_start"][pre] = np.minimum(out["minutes_to_start"][pre], to_start[pre])
        out["minutes_since_end"][post] = np.minimum(out["minutes_since_end"][post], since_end[post])
    return out


def load_weather() -> pd.DataFrame:
    w = pd.read_csv(ROOT / "data" / "weather" / "nyc_central_park_2024-08.csv")
    w["t"] = pd.to_datetime(w.obs_time).dt.tz_convert("America/New_York").dt.tz_localize(None)
    return w[["t", "rain"]].sort_values("t")


def load_nyc_events() -> pd.DataFrame:
    e = pd.read_csv(ROOT / "data" / "events" / "nyc_events_2024-08.csv")
    e = e[e.start.notna() & e.end.notna()].copy()
    for c in ("scheduled_start", "start", "end"):
        e[c] = pd.to_datetime(e[c], utc=True).dt.tz_convert("America/New_York").dt.tz_localize(None)
    return e


def median_event_minutes(e: pd.DataFrame) -> float:
    """Median actual game length on TRAIN days (Aug 1-21) -> assumed duration from the scheduled start."""
    tr = e[e.start < "2024-08-22"]
    return float(((tr.end - tr.start).dt.total_seconds() / 60).median())


def _minutes(ts) -> np.ndarray:
    """Minutes since epoch, independent of the datetime64 unit (ns or us)."""
    ts = pd.Series(pd.to_datetime(pd.Series(ts)))
    return ((ts - pd.Timestamp(0)) / pd.Timedelta(minutes=1)).to_numpy(dtype=float)


def build_frame(z: pd.DataFrame) -> pd.DataFrame:
    """z: windows (zone, bucket, idx, n, split) sorted by zone, bucket -> features + targets."""
    z = z.sort_values(["zone", "bucket"]).reset_index(drop=True)
    df = pd.concat([z, time_features(z.bucket)], axis=1)
    w = load_weather()
    df = pd.merge_asof(df.sort_values("bucket"), w, left_on="bucket", right_on="t",
                       direction="backward").drop(columns="t")
    df["rain"] = df.rain.fillna(0).astype(int)
    df = df.sort_values(["zone", "bucket"]).reset_index(drop=True)

    for c in EVENT:
        df[c] = FAR if c.startswith("minutes") else 0.0
    ev = load_nyc_events()
    dur = median_event_minutes(ev)
    for zone, g in ev.groupby("zone_id"):
        m = (df.zone == zone).to_numpy()
        s = _minutes(g.scheduled_start)
        f = event_features(_minutes(df.bucket[m]), s, s + dur)
        for c, v in f.items():
            df.loc[m, c] = v
    on_event_day = df.zone.isin(ev.zone_id) & df.bucket.dt.date.isin(set(ev.scheduled_start.dt.date))
    assert df.loc[~on_event_day, "event_nearby"].eq(0).all(), "event features leak outside event days"
    df["level"] = df.idx_a

    # targets: same zone, exactly h minutes later, on trip-half B; never across a split boundary
    key = df.set_index(["zone", "bucket"])
    for h in HORIZONS:
        fut = pd.MultiIndex.from_arrays([df.zone, df.bucket + pd.Timedelta(minutes=h)])
        same_split = key.split.reindex(fut).to_numpy() == df.split.to_numpy()
        r = key.idx_b.reindex(fut).to_numpy() / df.idx_b.to_numpy()
        df[f"ratio_{h}"] = np.where(same_split, r, np.nan)
        df[f"drop10_{h}"] = (df[f"ratio_{h}"] <= 0.9).astype(float).where(df[f"ratio_{h}"].notna())
    return df


def serve_row(local_dt: datetime, rain: bool, event_start: datetime | None = None,
              event_end: datetime | None = None, level: float | None = None) -> pd.DataFrame:
    """One feature row for the API. local_dt and event times on the pickup's local clock."""
    ts = pd.Series([pd.Timestamp(local_dt.replace(tzinfo=None))])
    row = time_features(ts)
    row["rain"] = int(rain)
    if event_start is not None and event_end is not None:
        f = event_features(_minutes(ts), _minutes([event_start.replace(tzinfo=None)]),
                           _minutes([event_end.replace(tzinfo=None)]))
    else:
        f = event_features(_minutes(ts), np.array([]), np.array([]))
    for c, v in f.items():
        row[c] = v
    if level is not None:
        row["level"] = float(np.clip(level, *LEVEL_RANGE))
    return row
