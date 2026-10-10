"""Out-of-time test: the FROZEN model (ml/models/lgbm_v1.joblib, trained on Aug 2024) on Sep 2024, a month it
never saw -> reports/holdout_sep2024.md / .json

Nothing is re-fit on September. The expected-fare formula (data/processed/base_fare.json) and the hour-of-day
baseline come from Aug 1-21 train days; k, thresholds, calibration and the assumed game length come from August.
Same windows, split-half noise control, targets and bootstrap as reports/metrics.md. September weather: NOAA
Central Park hourly (same station). September events: MLB home games at Yankee Stadium / Citi Field from the MLB
Stats API (no setlist.fm concerts were collected for September).

Verdict rules, fixed in this file and committed BEFORE the first run:
  V1  served "Wait" rule (with_level: odds >= k, P >= 20%, expected price falling, calibration cap) saves money vs
      book now: 95% CI of the mean saving > 0                                       -> HOLDS / DOES NOT HOLD
  V2  vs the hour-of-day rule: paired difference CI                                  -> beats / ties / loses
  V3  P(drop >= 10% @ +30, with_level) is better than the August base rate: Brier lower -> HOLDS / DOES NOT HOLD
  V4  high prices fall back: windows at level >= 1.5 have a mean +30 change with 95% CI < 0 -> HOLDS / DOES NOT HOLD
Usage: python -m ml.holdout_sep data/raw/fhvhv_tripdata_2024-09.parquet
"""
import csv
import io
import json
import subprocess
import sys
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from sklearn.metrics import brier_score_loss, roc_auc_score

import ml.features as F
from ml import fetch_nyc_events as EV
from ml import fetch_weather as W
from ml.build_dataset import COLS, MIN_HALF, MIN_TRIPS
from ml.evaluate import decide, paired_diff, pct, policy_stats
from ml.features import HORIZONS
from ml.train import MIN_WAIT_P, MODEL, base_rates, drop_prob, load_frame, mean_ratios, odds_multiples, tunggu

ROOT = Path(__file__).resolve().parent.parent
PROC = ROOT / "data" / "processed"
WEATHER = ROOT / "data" / "weather" / "nyc_central_park_2024-09.csv"
EVENTS = ROOT / "data" / "events" / "nyc_events_2024-09.csv"
REPORT = ROOT / "reports" / "holdout_sep2024.md"
START, END = "2024-09-01", "2024-10-01"


def fetch_weather() -> None:
    if WEATHER.exists():
        return
    W.URL = W.URL.replace("startDate=2024-07-31&endDate=2024-09-02", "startDate=2024-08-31&endDate=2024-10-02")
    W.OUT = WEATHER
    W.main()


def fetch_events() -> None:
    if EVENTS.exists():
        return
    rows = []
    for team, venue in EV.TEAMS.items():
        sched = EV.get(f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId={team}"
                       "&startDate=2024-08-31&endDate=2024-10-01")
        for d in sched["dates"]:
            for g in d["games"]:
                if g["venue"]["name"] != venue or g["status"]["detailedState"] != "Final":
                    continue
                pk = g["gamePk"]
                url = f"https://statsapi.mlb.com/api/v1.1/game/{pk}/feed/live"
                info = EV.get(url + "?fields=gameData,gameInfo,firstPitch,gameDurationMinutes,attendance")
                info = info["gameData"]["gameInfo"]
                start = datetime.fromisoformat(info["firstPitch"].replace("Z", "+00:00")).astimezone(EV.NY)
                end = start + timedelta(minutes=info["gameDurationMinutes"])
                zone, lat, lon = EV.VENUES[venue]
                sch = datetime.fromisoformat(g["gameDate"].replace("Z", "+00:00")).astimezone(EV.NY)
                rows.append(dict(id=f"mlb-{pk}", name=f"MLB: {g['teams']['away']['team']['name']} at "
                                 f"{g['teams']['home']['team']['name']}", venue=venue, zone_id=zone, lat=lat, lon=lon,
                                 date=start.date().isoformat(), scheduled_start=sch.isoformat(), start=start.isoformat(),
                                 end=end.isoformat(), attendance=info.get("attendance", ""), source_url=url))
    rows.sort(key=lambda r: r["start"])
    with EVENTS.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} MLB home games -> {EVENTS}")


def sep_windows(path: Path) -> pd.DataFrame:
    """Same windows as build_dataset.py, priced with the AUGUST expected-fare formula."""
    coef = json.loads((PROC / "base_fare.json").read_text())["coef"]
    pf = pq.ParquetFile(path)
    parts, rng, n_trips = [], np.random.default_rng(0), 0
    for i in range(pf.num_row_groups):
        d = pf.read_row_group(i, columns=COLS).to_pandas().dropna()
        d = d[(d.base_passenger_fare > 0) & (d.trip_miles > 0.2) & (d.trip_time > 60)]
        d["t"] = pd.to_datetime(d.request_datetime)
        d = d[(d.t >= START) & (d.t < END)]
        d["mins"] = d.trip_time / 60.0
        exp = np.full(len(d), np.nan)
        for lic, c in coef.items():
            m = (d.hvfhs_license_num == lic).values
            exp[m] = c[0] + c[1] * d.trip_miles.values[m] + c[2] * d.mins.values[m]
        d = d.assign(idx=np.clip(d.base_passenger_fare.values / exp, 0.3, 3.0))
        d = d[np.isfinite(d.idx) & (exp > 1)]
        n_trips += len(d)
        d["bucket"] = d.t.dt.floor("15min")
        half_a = rng.random(len(d)) < 0.5
        d = d.assign(sa=np.where(half_a, d.idx, 0.0), na=half_a.astype(int),
                     sb=np.where(half_a, 0.0, d.idx), nb=(~half_a).astype(int))
        g = d.groupby(["PULocationID", "bucket"])
        parts.append(pd.concat([g.idx.agg(["sum", "count"]), g[["sa", "na", "sb", "nb"]].sum()], axis=1))
    z = pd.concat(parts).groupby(level=[0, 1]).sum().reset_index()
    z = z.rename(columns={"PULocationID": "zone", "count": "n", "na": "n_a", "nb": "n_b"})
    z["idx"] = z["sum"] / z["n"]
    z["idx_a"] = z.sa / z.n_a.where(z.n_a > 0)
    z["idx_b"] = z.sb / z.n_b.where(z.n_b > 0)
    z = z[(z.n >= MIN_TRIPS) & (z.n_a >= MIN_HALF) & (z.n_b >= MIN_HALF)].drop(columns=["sum", "sa", "sb"])
    z["split"] = "holdout"
    print(f"September trips used: {n_trips:,}; windows: {len(z):,} in {z.zone.nunique()} zones")
    return z.sort_values(["zone", "bucket"]).reset_index(drop=True), n_trips


def sep_frame(z: pd.DataFrame) -> pd.DataFrame:
    aug_minutes = F.median_event_minutes(F.load_nyc_events())  # assumed game length: AUGUST train games

    def weather():
        w = pd.read_csv(WEATHER)
        w["t"] = pd.to_datetime(w.obs_time).dt.tz_convert("America/New_York").dt.tz_localize(None)
        return w[["t", "rain"]].sort_values("t")

    def events():
        e = pd.read_csv(EVENTS)
        for c in ("scheduled_start", "start", "end"):
            e[c] = pd.to_datetime(e[c], utc=True).dt.tz_convert("America/New_York").dt.tz_localize(None)
        return e

    F.load_weather, F.load_nyc_events, F.median_event_minutes = weather, events, lambda e: aug_minutes
    return F.build_frame(z)


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "raw" / "fhvhv_tripdata_2024-09.parquet"
    b = joblib.load(MODEL)
    aug = load_frame()  # August frame (before any monkeypatching): hour-of-day baseline + base rates
    tr = aug[aug.split == "train"]
    fetch_weather()
    fetch_events()
    z, n_trips = sep_windows(path)
    te = sep_frame(z)
    rcols = [f"ratio_{h}" for h in HORIZONS]
    te = te.dropna(subset=rcols).reset_index(drop=True)
    actual = te[rcols].to_numpy()
    clusters = (te.zone.astype(str) + "_" + te.bucket.dt.date.astype(str)).to_numpy()

    hour_avg = {h: tr.groupby("hour")[f"ratio_{h}"].mean() for h in HORIZONS}
    ha = np.c_[[te.hour.map(hour_avg[h]).to_numpy() for h in HORIZONS]].T
    hour_pol = decide(ha, None)

    rows, served = {"Book now (always)": policy_stats(np.zeros(len(te), bool), np.zeros(len(te), int), actual, clusters),
                    "Hour-of-day average ratio (Aug train)": policy_stats(*hour_pol, actual, clusters)}, {}
    p30 = {}
    for v in ("no_level", "with_level"):
        X = te[b["features"][v]]
        served[v] = tunggu(odds_multiples(b, v, X), b["wait_k"][v], base_rates(b), mean_ratios(b, v, X))
        rows[f"When Yah? served Wait rule, {v}"] = policy_stats(*served[v], actual, clusters)
        p30[v] = drop_prob(b["models"][v][30], X)
    y30 = (actual[:, 1] <= 0.9).astype(int)
    d_m, d_lo, d_hi = paired_diff(served["with_level"], hour_pol, actual, clusters)
    wl = rows["When Yah? served Wait rule, with_level"]
    brier_m = brier_score_loss(y30, p30["with_level"])
    brier_b = brier_score_loss(y30, np.full(len(y30), b["base_rate"][30]))
    hi15 = te.level.to_numpy() >= 1.5
    ch = actual[hi15, 1] - 1
    uc = np.unique(clusters[hi15])
    idx = {c: np.flatnonzero(clusters[hi15] == c) for c in uc}
    rng = np.random.default_rng(2)
    boots = [ch[np.concatenate([idx[c] for c in rng.choice(uc, len(uc))])].mean() for _ in range(500)]
    surge = {"windows": int(hi15.sum()), "change_30": float(ch.mean()), "ci": [float(np.percentile(boots, 2.5)),
             float(np.percentile(boots, 97.5))], "drop10_actual": float((actual[hi15, 1] <= 0.9).mean()),
             "drop10_model": float(p30["with_level"][hi15].mean())}
    v = {"V1_wait_saves": bool(wl["lo"] > 0),
         "V2_vs_hour_of_day": "beats" if d_lo > 0 else "loses to" if d_hi < 0 else "ties",
         "V3_calibration_beats_base_rate": bool(brier_m < brier_b),
         "V4_high_prices_fall_back": bool(surge["ci"][1] < 0)}
    cal = [{"mean_predicted": round(float(g.p.mean()), 4), "observed": round(float(g.y.mean()), 4), "windows": int(len(g))}
           for _, g in pd.DataFrame({"p": p30["with_level"], "y": y30}).groupby(
               pd.qcut(p30["with_level"], 10, duplicates="drop"), observed=True)]

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    L = ["# Out-of-time test: September 2024 (model frozen, trained on August)", "",
         f"Generated by `python -m ml.holdout_sep` on {date.today().isoformat()} (code at commit `{commit}`; verdict rules "
         "fixed in the code before the first run). Data: NYC TLC High Volume FHV trips, Sep 2024 "
         f"({n_trips:,} trips used), file `{path.name}` (source and check: see the end). Nothing was re-fit on September.",
         f"Test windows with all four horizons: **{len(te):,}** in {te.zone.nunique()} zones, {te.bucket.dt.date.nunique()} days.", "",
         "## Verdicts (rules fixed before running)",
         f"- **V1 Wait rule saves money vs book now:** {'HOLDS' if v['V1_wait_saves'] else 'DOES NOT HOLD'} — "
         f"{pct(wl['saving'])} ({pct(wl['lo'])} … {pct(wl['hi'])}); waits {wl['wait_rate']:.1%}, saves {pct(wl['saving_when_wait'])} "
         f"when it waits, {wl['worse_share_of_waits']:.0%} of waits cost more.",
         f"- **V2 vs the hour-of-day rule:** {v['V2_vs_hour_of_day']} (paired difference {pct(d_m)}, 95% CI {pct(d_lo)} … {pct(d_hi)}).",
         f"- **V3 chances better than the base rate:** {'HOLDS' if v['V3_calibration_beats_base_rate'] else 'DOES NOT HOLD'} "
         f"(Brier {brier_m:.4f} vs {brier_b:.4f}); ROC-AUC {roc_auc_score(y30, p30['with_level']):.3f} (August: 0.589).",
         f"- **V4 high prices fall back:** {'HOLDS' if v['V4_high_prices_fall_back'] else 'DOES NOT HOLD'} — at ≥ 1.5× "
         f"({surge['windows']} windows) the price changed {pct(surge['change_30'], 1)} in 30 min (95% CI {pct(surge['ci'][0], 1)} … "
         f"{pct(surge['ci'][1], 1)}); a ≥ 10% drop happened {surge['drop10_actual']:.0%} of the time (model said {surge['drop10_model']:.0%}).",
         "", "## Policies (September)", "",
         "| Policy | Waits | Mean saving vs book now (95% CI) | Saving when it waits | Waits that cost more |", "|---|---|---|---|---|"]
    for k, s in rows.items():
        L.append(f"| {k} | {s['wait_rate']:.1%} | {pct(s['saving'])} ({pct(s['lo'])} … {pct(s['hi'])}) | "
                 f"{pct(s['saving_when_wait'])} | {s['worse_share_of_waits']:.1%} |")
    L += ["", "## Calibration, with_level +30 min (September, predicted-probability deciles)", "",
          "| Mean predicted | Observed rate | Windows |", "|---|---|---|"]
    L += [f"| {c['mean_predicted']:.3f} | {c['observed']:.3f} | {c['windows']:,} |" for c in cal]
    L += ["", "## Notes",
          "- The served rule here includes the rising-price guard and the calibration cap (added 10 Oct); the August",
          "  numbers in reports/metrics.md do not. This is the first held-out test of the rule as served.",
          "- September events: MLB home games only (no concerts collected), from the MLB Stats API.",
          "- Still New York data: this shows the result holds in a new month, not that it holds in Kuala Lumpur."]
    REPORT.write_text("\n".join(L) + "\n", encoding="utf-8")
    REPORT.with_suffix(".json").write_text(json.dumps({
        "source": "reports/holdout_sep2024.md", "trips": n_trips, "windows": int(len(te)), "verdicts": v,
        "policies": [{"name": k, "wait_rate": round(float(s["wait_rate"]), 4), "saving": round(float(s["saving"]), 5),
                      "saving_ci": [round(float(s["lo"]), 5), round(float(s["hi"]), 5)],
                      "saving_when_wait": round(float(s["saving_when_wait"]), 4),
                      "waits_cost_more": round(float(s["worse_share_of_waits"]), 3)} for k, s in rows.items()],
        "vs_hour_of_day": [round(d_m, 5), round(d_lo, 5), round(d_hi, 5)],
        "brier": [round(brier_m, 5), round(brier_b, 5)], "auc_30": round(float(roc_auc_score(y30, p30["with_level"])), 3),
        "surge_ge_1_5": surge, "calibration_with_level_30": cal}, indent=1), encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
