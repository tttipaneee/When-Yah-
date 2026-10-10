# When Yah?

Dormathon 2026 · Track 1: Predictive Model ("Predict Early, Decide Better").

At peak hours, should you book your ride now or wait? Type the price you see in Grab, inDrive or
GV Ride, and When Yah? predicts how it will change over the next 60 minutes, tells you when to book,
which of your quoted apps is likely cheapest then, and which real events nearby may push prices up.

Every number traces to real data or a cited source: the model is trained and tested on public
ride-hailing data; prices come from what you type. Not connected to Grab, inDrive or GV Ride.

## Start here
- `docs/PRD.md` — requirements, timeline split between the two of us, demo script, cut list
- `CLAUDE.md` — instructions Claude Code reads every session
- `.claude/rules/`, `.claude/agents/` — module rules and review helpers
- `design/` — screen designs (Partner)
- `KICKOFF_PROMPT.md` — first message to paste into Claude Code

## Run it
```bash
pip install -r requirements.txt && (cd web && npm install)   # setup (Python 3.11+, Node 20+)
scripts/download_data.sh                                      # NYC HVFHV Aug 2024 -> data/raw/ (sha256-checked)
scripts/run_demo.sh                                           # API :8000 + web :3000
python -m pytest -q tests                                     # API contract tests
```
`/api/forecast` uses LightGBM models trained on real NYC Uber/Lyft trips (Aug 2024), committed at
`ml/models/lgbm_v1.joblib` (`lgbm_v1/with_level` when a usual price is given, else `lgbm_v1/no_level`).
RM values are always the user's typed quote × a predicted % change. `GET /api/demo` runs four presenter
scenarios (example prices, labelled "contoh").

## What it does — and what we found (every number from `reports/`)
The headline is **the chance that waiting 30 min gets a price ≥ 10% lower**, next to the usual chance.

| Claim | Number | Source |
|---|---|---|
| Odds are calibrated (test days, isotonic fit on val) | top decile: predicted 23.3%, observed 23.3% | `reports/metrics.md` §2 |
| Odds rise with "price ÷ usual price" | jam demo (≈1.9× usual): 45% vs usual 12% | `GET /api/demo` |
| Ranking good vs bad moments | ROC-AUC 0.589 (0.5 = coin flip) | `reports/metrics.md` §2 |
| Any waiting rule beats "book now" **and** "hour-of-day"? | **No** — best tested rule +0.11% vs hour-of-day +0.29% | `reports/decision.json` |

So the app says **book now** and shows the odds as information, until a tested rule beats both baselines.

**Tested and rejected** (rules fixed in code before each run): a second quote / price trend
(`reports/trend_experiment.md`), borough-wide averaging (`reports/borough_experiment.md`, inconclusive),
traffic and "why is it high" (`reports/traffic_experiment.md`), applying the NYC event effect to KL
(`reports/event_effect.md` — validated only for Yankee Stadium baseball). Two leakage audits found and
removed a noise leak that had inflated our first savings numbers.

## Model card
- **Data:** NYC TLC High Volume FHV trips, Aug 2024 (19,128,392 rows, sha256-checked); NOAA Central Park
  hourly weather; MLB games from statsapi.mlb.com. Split by day: train Aug 1–21, val 22–25, test 26–31.
- **Target:** price index (fare ÷ expected fare for distance + time) 15–60 min later, on an independent
  half of the trips (split-half noise control).
- **Inputs served:** hour, minute, weekday, rain toggle, and level = typed price ÷ usual price. No area IDs.
- **Limits:** learned in New York, applied to Klang Valley clocks; outcomes are zone averages, not one
  rider's re-quote; not connected to Grab, inDrive or GV Ride. Route-based usual-price estimate is off
  until `reports/fare_check.md` passes on our own real off-peak quotes.
