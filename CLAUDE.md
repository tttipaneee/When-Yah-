# When Yah? — Claude instructions

Dormathon 2026 · Track 1: Predictive Model ("Predict Early, Decide Better").
Team: **Ravin** (data, model, API) · **Partner** (design, frontend, slides, pitch).
Hard submission: **Sun 11 Oct 2026 09:00 MYT** (aim 08:30).

Full product requirements: `docs/PRD.md` — read it before planning a feature or when scope is unclear.
Module rules load automatically from `.claude/rules/` (ml.md, api.md, web.md).

## What we're building
At peak hours people open Grab, inDrive and GV Ride one by one and still don't know if the price will
drop if they wait. The user types the price(s) they see; **When Yah?** predicts how that price will
change over the next 60 minutes and says **book now or wait (until when)**, which of their quoted apps
is likely cheapest at the best time, and warns when a real event nearby is likely to push prices up.

## The evidence rule — never break it
Every number shown in the app, README or slides must trace to **real data** or a **cited, dated source**.
- **Real data:** model trained and evaluated on public ride-hailing data (NYC TLC High Volume FHV trip records, Uber/Lyft, Aug 2024). Boston was rejected at go/no-go — see `reports/signal_check.md`.
- **Real input:** prices the user types from their own apps ("Masukkan harga yang anda nampak"), optional usual price ("harga biasa").
- **Learned from real data, only if validated:** event effect from real NYC venue events (e.g. Madison Square Garden, Barclays Center, Yankee Stadium; Aug 2024, sourced) — shown only if `reports/event_effect.md` confirms it on held-out data.
- **Cited sources:** real Malaysian event schedules (venue, date, time, source URL); 2× surcharge ceiling (Ministry of Transport statement, May 2022 — cite with date).
- **Not allowed:** invented fares, multipliers, per-app RM prices, area adjustments or event uplifts. If a value can't be traced, don't show it.
- We are **not** connected to Grab, inDrive or GV Ride. Never claim it; never scrape or automate their apps.

## Repo map
```
data/raw/        downloaded public datasets + game schedules (gitignored)
data/processed/  price-index time series (parquet)
data/events/     malaysia_events.csv (real events with source URLs)
ml/              check_signal.py · build_dataset.py · features.py · event_effect.py · train.py · evaluate.py · models/
api/             FastAPI: main.py · forecast.py · events.py · routes/
web/             Vite + React + TS (design from Partner in design/)
reports/         signal_check.md · metrics.md · event_effect.md (only sources for numbers)
scripts/         run_demo.sh
```

## Commands
Fill in as they're created; keep them working.
- Setup: `pip install -r requirements.txt && (cd web && npm install)`
- Download data: `scripts/download_data.sh` (sha256-verified, 19,128,392 rows)
- NYC venue events: `python ml/fetch_nyc_events.py` → `data/events/nyc_events_2024-08.csv`
- Weather (NOAA Central Park hourly): `python ml/fetch_weather.py` → `data/weather/nyc_central_park_2024-08.csv`
- Check data signal (go/no-go): `python ml/check_signal_nyc.py data/raw/fhvhv_tripdata_2024-08.parquet`
- Build dataset / event effect / train / evaluate: `[TBD]`
- API tests: `python -m pytest -q tests`
- Run demo (API + web): `scripts/run_demo.sh` → web http://localhost:5173, API http://localhost:8000/docs

## API contract (shared by frontend and backend)
- `GET /api/events?date=YYYY-MM-DD` → `[{id, name, venue, lat, lon, start, end, source_url}]`
- `POST /api/forecast` body
  `{datetime, rain: bool, pickup: {lat, lon} | null, quotes: [{app, price_rm}], usual_price_rm: number | null}` →
```json
{"datetime": "2026-10-10T18:10:00+08:00",
 "horizon": [{"minutes": 15, "pct_change": -0.06, "pct_low": -0.14, "pct_high": 0.03, "p_drop10": 0.41,
              "expected_rm": {"grab": 35.7}}],
 "decision": "wait", "best_time": "2026-10-10T18:35:00+08:00", "wait_minutes": 25,
 "expected_saving_rm": {"grab": 4.2}, "risk_if_wait_rm": {"grab": 1.1},
 "apps_ranked_now": ["indrive", "grab"], "apps_ranked_best_time": ["grab", "indrive"],
 "events": [{"name": "...", "source_url": "...", "learned_effect": {"pct": 0.22, "window": "0–45 min after end"}}],
 "reasons": ["Friday evening peak typically eases after 18:30 in training data", "no rain"],
 "model_version": "lgbm_v1", "evidence": {"metrics": "reports/metrics.md"}}
```
- `expected_rm`, savings and rankings exist **only for apps the user quoted**; with no quotes, return percentages only.
- `learned_effect` is `null` unless `reports/event_effect.md` validated it; then the event is listed without a number.
- Horizons: 15, 30, 45, 60 minutes. `decision` ∈ `book_now | wait`. `quotes[].app` ∈ `grab | indrive | gvride` (else 422).
- `/api/events` and forecast `events`: real rows from `data/events/malaysia_events.csv`; with a pickup, only events within 5 km.
- `GET /api/metrics` → contents of `reports/metrics.md` and `reports/event_effect.md` as JSON.
Changing the contract: update this section and tell both teammates.

## Subagents (`.claude/agents/`)
- `signal-checker` — 14:00 go/no-go: does price move enough over time, and is there a game-night effect?
- `leakage-auditor` — after changing ml/, and before any number goes on a slide.
- `submission-checker` — at feature freeze (04:00) and before submitting; also enforces the evidence rule.
They report only; fix findings in the main session.

## Rules
1. **Evidence rule above, always.** No traceable source → no number.
2. **Time-based splits only.** Earlier days train, later days test. Features use only information available at time t.
3. **Area-agnostic served model.** NYC zone IDs may be used in analysis but not as features in the model served for Malaysia.
4. **Always compare to baselines:** "book now" and "hour-of-day average ratio". If we don't beat them, say so.
5. **Location:** one-time browser geolocation with permission, used only to find nearby events; never stored.
6. **Demo path first.** Keep quote → forecast → decision working end-to-end. Stub `/api/forecast` until the real model passes evaluation.
7. **Time-box 45 minutes.** If stuck, use the cut list in `docs/PRD.md` §9.
8. **Simple over clever.** LightGBM/linear models; no deep learning; justify heavy dependencies in one line.
9. **Secrets only in `.env`.** Never commit or print them.
10. **Commit after each working milestone**; never leave `main` broken. One command per task, documented above.
11. **Work autonomously.** Report what was done, what's next, and any risk to the 14:00 go/no-go and 19:00 end-to-end checkpoints. Ask only for irreversible or genuinely ambiguous decisions.
12. **Verify before claiming done:** run it, show the output.
