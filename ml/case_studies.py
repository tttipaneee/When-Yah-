"""Two "perfect scenario" case studies on real data -> reports/case_studies.md + reports/case_*.png

1. EVENT EXIT (Yankee Stadium, TLC zone 247, MLB home games Aug 2024). Price index in the venue's zone by
   minutes relative to the game's end, divided by the same zone at the same clock time on non-game days
   (train period) - 1. "Model" = the average curve of TRAIN games (Aug 1-21), fitted per 15-min bin.
   Test = held-out games (Aug 22-31): does the train curve predict their curve better than "no event effect"?
2. SURGE FALL-BACK (all zones, test days Aug 26-31). For windows where the current price is already high
   (level = price / expected, from trip-half A), what actually happened over the next 15-60 min (trip-half B),
   and did the served with_level model predict it?
Dev-only dependency: matplotlib (charts). Usage: python -m ml.case_studies
"""
from datetime import date
from pathlib import Path

import joblib
import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from ml.features import HORIZONS, load_nyc_events  # noqa: E402
from ml.train import MODEL, drop_prob, load_frame  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REP = ROOT / "reports"
BLUE, ORANGE, INK, MUTED, GRID = "#2a78d6", "#eb6834", "#0b0b0b", "#52514e", "#e4e3df"
BINS = list(range(-120, 121, 15))  # minutes relative to game end (bin start)


def style(ax, title, ylabel):
    ax.set_title(title, loc="left", fontsize=12, color=INK, pad=10)
    ax.set_ylabel(ylabel, color=MUTED)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(GRID)
    ax.tick_params(colors=MUTED)
    ax.axhline(0, color=MUTED, linewidth=0.8, linestyle=(0, (3, 3)))


def event_curves(z: pd.DataFrame, games: pd.DataFrame, ctrl_days: set) -> pd.DataFrame:
    """Per game x 15-min bin: uplift of the zone index vs same clock time on non-game train days."""
    zz = z[z.zone == 247].copy()
    zz["tod"] = zz.bucket.dt.time
    ctrl = zz[zz.bucket.dt.date.isin(ctrl_days)].groupby("tod").idx.mean()
    rows = []
    for _, g in games.iterrows():
        rel = (zz.bucket - g.end).dt.total_seconds() / 60
        w = zz[(rel >= BINS[0]) & (rel < BINS[-1] + 15)].assign(rel=rel)
        for b in BINS:
            x = w[(w.rel >= b) & (w.rel < b + 15)]
            if len(x) and x.tod.iloc[0] in ctrl.index:
                rows.append(dict(game=g.id, bin=b, uplift=x.idx.mean() / ctrl[x.tod.iloc[0]] - 1))
    return pd.DataFrame(rows)


def case_event(L: list) -> None:
    z = pd.read_parquet(ROOT / "data" / "processed" / "windows.parquet")
    ev = load_nyc_events()
    ev = ev[(ev.zone_id == 247) & ev.id.str.startswith("mlb-")]
    game_days = set(ev.start.dt.date)
    train_days = {d for d in pd.date_range("2024-08-01", "2024-08-21").date if d not in game_days}
    tr = ev[ev.start < "2024-08-22"]
    te = ev[(ev.start >= "2024-08-22") & (ev.start < "2024-09-01")]
    ctr, cte = event_curves(z, tr, train_days), event_curves(z, te, train_days)
    fit = ctr.groupby("bin").uplift.mean()  # the fitted "model": average post-game curve on TRAIN games
    held = cte.groupby("bin").uplift.mean()
    cte["pred"] = cte.bin.map(fit)
    mae_model = (cte.uplift - cte.pred).abs().mean()
    mae_none = cte.uplift.abs().mean()
    post = cte[(cte.bin >= 0) & (cte.bin < 45)]
    peak_bin = fit[fit.index >= 0].idxmax()

    fig, ax = plt.subplots(figsize=(7.2, 3.8), dpi=160)
    style(ax, "Yankee Stadium area: price vs a normal day, around the end of the game", "price vs normal day")
    ax.plot(fit.index + 7.5, fit.values * 100, color=BLUE, linewidth=2, marker="o", markersize=4,
            label=f"Learned from {len(tr)} training games (Aug 1–21)")
    ax.plot(held.index + 7.5, held.values * 100, color=ORANGE, linewidth=2, marker="o", markersize=4,
            label=f"Actual, {len(te)} held-out games (Aug 22–31)")
    ax.axvline(0, color=INK, linewidth=1)
    ax.text(2, ax.get_ylim()[1] * 0.92, "game ends", color=INK, fontsize=9)
    ax.set_xlabel("minutes from end of game", color=MUTED)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:+.0f}%"))
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    fig.tight_layout(); fig.savefig(REP / "case_event_exit.png"); plt.close(fig)

    L += ["## 1. Event exit — Yankee Stadium (real MLB games, Aug 2024)", "",
          "Price index in the stadium's own taxi zone (~0.75 km radius) by minutes from the end of the game, vs the",
          "same zone at the same clock time on non-game days. The **model** is the average curve of the training games;",
          "it is tested on games it never saw.", "", "![event exit](case_event_exit.png)", "",
          f"- Training games: {len(tr)}; held-out games: {len(te)} (all Yankee Stadium; Citi Field had no home games in the test days).",
          f"- Learned pattern: prices peak **{fit[peak_bin]:+.0%}** at {peak_bin}–{peak_bin + 15} min after the end, "
          f"then ease (bin means: " + ", ".join(f"{b:+d}: {v:+.0%}" for b, v in fit.items() if -30 <= b <= 90) + ").",
          f"- Held-out games, 0–45 min after the end: actual **{post.uplift.mean():+.0%}** vs learned "
          f"{post.pred.mean():+.0%}.",
          f"- Prediction error on held-out games (all bins): learned curve **{mae_model:.1%}** vs \"no event effect\" "
          f"{mae_none:.1%} → the learned curve is {'better' if mae_model < mae_none else 'NOT better'}.",
          "- Caveat: one venue, a handful of held-out games, baseball crowds in New York. Not measured in Malaysia.", ""]


def case_surge(L: list) -> None:
    b = joblib.load(MODEL)
    df = load_frame()
    te = df[df.split == "test"].dropna(subset=[f"ratio_{h}" for h in HORIZONS]).reset_index(drop=True)
    f = b["features"]["with_level"]
    ms = b["models"]["with_level"]
    bands = [("normal (< 1.2×)", te.level < 1.2), ("1.2–1.5×", (te.level >= 1.2) & (te.level < 1.5)),
             ("≥ 1.5×", te.level >= 1.5), ("≥ 1.8×", te.level >= 1.8)]
    rows = []
    for name, m in bands:
        t = te[m]
        X = t[f]
        for h in HORIZONS:
            rows.append(dict(band=name, h=h, n=len(t), actual=(t[f"ratio_{h}"] - 1).mean(),
                             pred=(ms[h]["mean"].predict(X) - 1).mean(),
                             drop_actual=(t[f"ratio_{h}"] <= 0.9).mean(), drop_pred=drop_prob(ms[h], X).mean()))
    r = pd.DataFrame(rows)

    fig, ax = plt.subplots(figsize=(7.2, 3.8), dpi=160)
    style(ax, "When the price is already ≥ 1.5× normal: what happened next", "price change vs now")
    s = r[r.band == "≥ 1.5×"]
    ax.plot([0] + list(s.h), [0] + list(s.actual * 100), color=ORANGE, linewidth=2, marker="o", markersize=4,
            label=f"Actual (test days, {int(s.n.iloc[0])} cases)")
    ax.plot([0] + list(s.h), [0] + list(s.pred * 100), color=BLUE, linewidth=2, marker="o", markersize=4,
            linestyle=(0, (4, 2)), label="Model's prediction for the same cases")
    nrm = r[r.band == "normal (< 1.2×)"]
    ax.plot([0] + list(nrm.h), [0] + list(nrm.actual * 100), color=MUTED, linewidth=1.5,
            label="Actual, normal prices (for comparison)")
    ax.set_xlabel("minutes waited", color=MUTED)
    ax.set_xticks([0] + list(HORIZONS))
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:+.0f}%"))
    ax.legend(frameon=False, fontsize=9, loc="lower left")
    fig.tight_layout(); fig.savefig(REP / "case_surge_fallback.png"); plt.close(fig)

    L += ["## 2. Surge fall-back — prices already far above normal (test days Aug 26–31)", "",
          "Level = current price ÷ expected price for the trip (from half of the trips); the outcome is measured on",
          "the other half, so noise cannot fake a fall-back. Model = the served with_level model.", "",
          "![surge fall-back](case_surge_fallback.png)", "",
          "| Price now | Cases | Actual change at +30 / +60 min | Model predicted | Actual chance of ≥10% drop by +30 | Model said |",
          "|---|---|---|---|---|---|"]
    for name, _ in bands:
        g = r[r.band == name].set_index("h")
        L.append(f"| {name} | {int(g.n.iloc[0]):,} | {g.actual[30]:+.1%} / {g.actual[60]:+.1%} | "
                 f"{g.pred[30]:+.1%} / {g.pred[60]:+.1%} | {g.drop_actual[30]:.0%} | {g.drop_pred[30]:.0%} |")
    L += ["", "- Reading: the higher the price is now, the more it falls back — and the model's predictions track the",
          "  actual averages. This is the situation where \"wait\" advice is grounded in data.",
          "- Caveat: mostly mean reversion (high prices settle on their own); a simple time-of-day rule saves about as",
          "  much overall (`reports/decision.json`). Learned on New York data, applied to KL clocks.", ""]


def main() -> None:
    L = ["# Case studies — where the data shows a clear, repeatable pattern", "",
         f"Generated by `python -m ml.case_studies` on {date.today().isoformat()} from real NYC TLC trip data "
         "(Aug 2024). Fitted on training days/games, checked on held-out ones.", ""]
    case_event(L)
    case_surge(L)
    (REP / "case_studies.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
