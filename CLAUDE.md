# When Yah? — Claude instructions

Dormathon 2026 · Track 1: Predictive Model ("Predict Early, Decide Better").
Team: **Ravin** (data, model, API) · **Partner** (design, frontend, slides, pitch).
Hard submission: **Sun 11 Oct 2026 09:00 MYT** (aim 08:30).

Full product requirements: `docs/PRD.md` — read it before planning a feature or when scope is unclear.
Module rules load automatically from `.claude/rules/` (ml.md, api.md, web.md).

## What we're building
At peak hours people open Grab, inDrive and GV Ride one by one and still don't know if the price will
drop if they wait. The user types the price(s) they see (usual price optional); **When Yah?** gives the
**calibrated odds that waiting 30 min gets a price ≥ 10% lower** (vs the usual odds), the likely RM range
per quoted app, "Wait X min" or book now (tested rule: beats book-now, slightly below hour-of-day), and real
events nearby with sources. Revised 10 Oct after testing — see `docs/PRD.md` §1 and §10.

## The evidence rule — never break it
Every number shown in the app, README or slides must trace to **real data** or a **cited, dated source**.
- **Real data:** model trained and evaluated on public ride-hailing data (NYC TLC High Volume FHV trip records, Uber/Lyft, Aug 2024). Boston was rejected at go/no-go — see `reports/signal_check.md`.
- **Real input:** prices the user types from their own apps ("Enter the prices you see"), optional usual price .
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
- Setup: `pip install -r requirements.txt && (cd web && npm install)`; optional `TOMTOM_API_KEY` in `.env` for traffic
- Download data: `scripts/download_data.sh` (sha256-verified, 19,128,392 rows)
- NYC venue events: `python ml/fetch_nyc_events.py` → `data/events/nyc_events_2024-08.csv`
- Weather (NOAA Central Park hourly): `python ml/fetch_weather.py` → `data/weather/nyc_central_park_2024-08.csv`
- Check data signal (go/no-go): `python ml/check_signal_nyc.py data/raw/fhvhv_tripdata_2024-08.parquet`
- Build dataset / train / evaluate: `python ml/build_dataset.py && python -m ml.train && python -m ml.evaluate` (→ `reports/metrics.md`)
- Event effect: `python -m ml.event_effect` (→ `reports/event_effect.md`)
- Trend experiment (second quote): `python -m ml.experiment_trend` (→ `reports/trend_experiment.md`)
- Borough experiment: `python -m ml.experiment_borough` (→ `reports/borough_experiment.md`; zone→borough from `data/zones/taxi_zones_borough.csv`, NYC Open Data taxi zones export 2025-10-03)
- Traffic: `python -m ml.traffic && python -m ml.experiment_traffic` (→ `reports/traffic_experiment.md`)
- Model v2 price line + reasons: `python -m ml.experiment_v2` (→ `reports/metrics_v2.md`, `reports/v2_verdict.json`, `ml/models/lgbm_v2.joblib`; first run builds the September frame from `data/raw/fhvhv_tripdata_2024-09.parquet`, cached in `data/processed/frame_sep.parquet`)
- Extreme-price calibration: `python -m ml.experiment_extreme` (→ `reports/extreme_experiment.md`)
- Case studies (event exit + surge fall-back, charts): `python -m ml.case_studies` (→ `reports/case_studies.md`, `reports/case_*.png`; needs matplotlib, dev only)
- Fare check (needs real off-peak quotes in `data/fares/offpeak_quotes.csv`): `python -m ml.fare_check` (→ `reports/fare_check.md`, gate for `usual_price_estimate`)
- API tests: `python -m pytest -q tests`
- Run demo (API + web): `scripts/run_demo.sh` → web http://localhost:3000, API http://localhost:8000/docs

## API contract (shared by frontend and backend)
- `GET /api/events?date=YYYY-MM-DD` → `[{id, name, venue, lat, lon, start, end, source_url}]` (`end` is `null` when no source publishes it)
- `POST /api/forecast` body
  `{datetime, rain: bool, pickup: {lat, lon} | null, quotes: [{app, price_rm}], usual_price_rm: number | null}` →
```json
{"datetime": "2026-10-10T18:10:00+08:00",
 "horizon": [{"minutes": 15, "pct_change": -0.06, "pct_low": -0.14, "pct_high": 0.03, "p_drop10": 0.41,
              "expected_rm": {"grab": 35.7}}],
 "wait_odds": {"minutes": 30, "p_save10": 0.33, "typical_p_save10": 0.125, "pct_low": -0.18, "pct_high": 0.14,
               "rm_range": {"grab": [31.3, 43.4]}},
 "decision": "wait", "best_time": "2026-10-10T18:35:00+08:00", "wait_minutes": 25,
 "expected_saving_rm": {"grab": 4.2}, "risk_if_wait_rm": {"grab": 1.1},
 "apps_ranked_now": ["indrive", "grab"], "apps_ranked_best_time": ["grab", "indrive"],
 "events": [{"name": "...", "source_url": "...", "learned_effect": {"pct": 0.22, "window": "0–45 min after end"}}],
 "reasons": ["Friday evening peak typically eases after 18:30 in training data", "no rain"],
 "model_version": "lgbm_v1", "evidence": {"metrics": "reports/metrics.md"}}
```
- `outlook: {minutes: 30, pct_change, pct_low, pct_high, because: [str], model} | null` — the one-line prediction,
  same numbers as `horizon` at +30. Since 11 Oct the shown line (`horizon[].pct_change/low/high`) comes from model v2
  (`ml/model_v2.py`: usual price for this time of week + how far the price is from the user's usual) for each variant
  where `reports/v2_verdict.json` passed (beat v1 and persistence on test days and Sep 2024); `model` = `lgbm_v2`, and
  `model_version` gets `+lgbm_v2_line`. `because` = the model's top SHAP groups in words (time of day / price vs
  normal / rain only if raining / event) — "main reasons in the model", never traffic; `reasons[1]` states it.
  `p_drop10`, `wait_odds` and the Wait/Book now rule stay v1 (the Wait rule's "falling" check uses v1's line).
- **`wait_odds` is the headline** (since 10 Oct): chance that waiting 30 min gets a price ≥ 10% lower, vs the
  typical chance (training base rate), plus the p10–p90 range. `reasons[0]` states the odds in words.
- `decision` = `wait` only if `reports/decision.json` → `variants[<variant>].validated` (beats book-now on test days,
  CI > 0) **and** the best 15–60 min odds multiple (P(drop≥10%) ÷ usual) is ≥ k **and** P(drop≥10%) there is ≥ 20%
  (product rule; below that, "book now") **and** the expected `pct_change` there is < 0 (product rule, 10 Oct: never
  "Wait" next to a rising line) **and** the expected saving there on the cheapest quote (quote × −`pct_change`, the saving shown) is ≥ RM 1.00 (product rule, 11 Oct; not applied without quotes); `wait_minutes` = that horizon.
  A reason starting "Wait" gives the tested saving and how often waiting cost more.
- `GET /api/route?from_lat&from_lon&to_lat&to_lon[&at]` → `{km, minutes, source}` (nulls without a TomTom key): trip time
  with traffic for leaving now (or a future `at`), one TomTom call cached per minute, so the map shows it before any
  forecast; after a forecast for the same route, the forecast's `traffic` is used. Minutes only.
- `GET /api/usual?from_lat&from_lon&to_lat&to_lon[&at]` → `usual_price_estimate` fields + `time_factor`, `rm_at_this_time`,
  `time_source` (model v2's usual-for-this-hour/weekday factor, reports/metrics_v2.md) | `{rm: null}`: shown on the price
  card as soon as both places are set ("Usual ≈ RM X · at this hour ≈ RM Y", rough label, also the field's placeholder).
  The forecast uses the formula value only.
- Optional request `dropoff: {lat, lon}`; with `pickup` it fills `usual_price_estimate: {rm, km, min, source, validated,
  median_abs_error, n_quotes}` (Grab Jan 2023 rates + TomTom route, else OSM route). If the user typed no usual price,
  it is used as the usual price (product decision, Ravin 11 Oct) — `validated: false` while `reports/fare_check.json`
  fails, and a reason says "No usual price typed: using an estimated usual price of RM X (… rough: off by N% (median)
  on M real quotes in our check)". A typed usual price always wins.
- Potential traffic: optional request `traffic_min: {minutes_from_now: trip_minutes}`; if absent and `pickup` + `dropoff`
  are given, the API asks TomTom Routing (traffic-aware, `departAt` now/+15/+30/+45/+60; needs `TOMTOM_API_KEY` in `.env`).
  Response `traffic: {source, minutes, jam_ahead, flipped_to_book_now, km} | null` (`km` = TomTom route length for
  leaving now; the map labels the route with `minutes["0"]` + `km`, else the OSRM no-traffic route). A departure ≥ 25% longer than now
  = jam: "Wait" flips to "Book now — jam coming". If a Grab quote's trip gets ≥ 10% (and 3 min) longer later, the reason adds
  that Grab's fare includes a per-minute charge (Grab fare structure, Jan 2023), in words only. Minutes only — traffic is **not** a price-model input
  (`reports/traffic_experiment.md`).
- Forecast also returns `situation` ∈ `jam_coming | event_exit | surge | pricey | rush_hour | normal` (first match:
  jam ahead, exit-hint window, level ≥ 1.5, level ≥ 1.2, expected rise ≥ 1.5%) and `urgency` ∈ `urgent | wait | no_gain`
  (`wait` iff decision is wait; `urgent` if jam ahead, event ending soon or rising). Labels only, no new numbers.
- "Booked? Tell us what you paid" card: app + RM paid, stored in the browser's localStorage (`whenyah.fares`) only,
  never sent; the thank-you compares the typed quote (and the expected price after waiting, if advised) with the fare paid.
- Points + Leaderboard (frontend only, localStorage `whenyah.points`): forecast the user asked for = 10 pts + 5 per
  extra quoted app (max 3), same route within 10 min = 0; fare report = 25 pts once per forecast; 150 pts/day cap.
  Leaderboard tab (trophy) + header points chip. The six friends are **labelled example data** ("Example friends — not
  real users"), scored around the user's points at first look each week. Leaderboard friends map (3D, MapLibre +
  OpenFreeMap, lazy-loaded): example friends at **made-up** central-KL spots, labelled "Example friends at made-up places";
  "You" only at the typed pickup if within 3 km. No real location sharing.
- Forecast page: Option 1 = verdict (Wait/Book now, one short line, ring); Option 2 = "Walk out of the zone" card,
  shown only when the forecast returns `walk_out` (else hidden).
- Forecast `walk_out: {event, venue, source_url, end, ended, center: {lat, lon}, radius_km, target: {lat, lon} | null,
  walk_km} | null`: whenever the pickup is `right_here` (≤ 1 km) of a venue with an event that day, any time
  (product choice, Ravin 11 Oct; `end`/`ended` null/false when no end is published). `target` = a point
  `HERE_KM + 0.2` km from the venue toward the drop-off (if outside the circle), else away from the venue through the
  pickup, else `null`; `walk_km` = straight line pickup → target. Words + map only, never a price % (the post-event rise
  is validated for NYC baseball only). "Show me on the map" zooms to the circle, pickup and a "Check prices here" point.
  "Make this my pickup" (or tapping that point) moves the pickup there (street name from OSM Nominatim reverse lookup,
  else "Walk-out point"), clears the typed prices (they were for the old spot) and returns to the price field.
- Presenter time: `?at=YYYY-MM-DDTHH:MM` in the web URL runs the forecast and that day's events at that KL time
  (e.g. `?at=2026-10-11T22:40` shows Option 2 for the Zepp KL concert ending 23:00).
- `POST /api/explain` (same body as forecast) → `{ai, text, model?, facts?, reason?}`: Claude (`claude-sonnet-5-5`, effort low, runs automatically as the "Why" text,
  server-side refusal fallback on) explains the server-recomputed forecast from a facts JSON only; any number in the
  answer that is not in the facts → rejected, `ai: false`. Needs `ANTHROPIC_API_KEY` in `.env`; without it `ai: false`.
- `GET /api/case_studies` → `reports/case_studies.json` (event exit curve, surge fall-back table; same numbers as
  `reports/case_studies.md`, checked by a test). Shown in the "What we saw in real ride data" card (no city named there).
- `GET /api/demo` → presenter scenarios `[{id, title, label: "example…", request, response}]` (real forecast, example prices).
- `expected_rm`, savings, `rm_range` and rankings exist **only for apps the user quoted**; with no quotes, return percentages only.
- `learned_effect` is `null` unless `reports/event_effect.md` is VALIDATED (API reads `reports/event_effect.json`) **and** the event has a published `end`; otherwise the event is listed without a number.
- Horizons: 15, 30, 45, 60 minutes. `decision` ∈ `book_now | wait`. `quotes[].app` ∈ `grab | indrive | gvride` (else 422).
- `/api/events` and forecast `events`: real rows from `data/events/malaysia_events.csv`; with a pickup, only events within 5 km.
  Forecast events carry `km` and `level`: `right_here` (≤ 1 km ≈ the venue's own NYC taxi zone, where post-game effects
  were measured) or `in_area` (≤ 5 km, product choice, information only). The map draws a dashed 1 km circle per venue.
  Exit hint: for a `right_here` event with a published `end`, from 30 min before to 45 min after it, a reason starting
  "Event ending right here" says in words (no %) that prices next to a venue went up after big events ended.
- Metrics tab opens the "How we know" Proof screen built only from `/api/metrics` (calibration dots, policy savings vs
  book-now and the time-of-day rule, ≥1.5× case, AUC, tested experiments, fare check).
- `GET /api/metrics` → `{metrics, event_effect}` (report texts) + `fare_check` (`reports/fare_check.json`) + `structured` (`reports/metrics.json`: policies, AUC,
  calibration table), `decision`, `event_effect_summary`, `experiments` (result lines of each experiment report).
- `learned_effect` is currently always `null` for Malaysian events (the validated effect is NYC baseball only).
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
