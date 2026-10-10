---
paths:
  - "ml/**"
  - "data/**"
  - "reports/**"
  - "api/forecast.py"
---

# ML & data rules — When Yah?

## Datasets
- **Primary:** NYC TLC High Volume FHV trips, Aug 2024 — `data/raw/fhvhv_tripdata_2024-08.parquet`
  (19 row groups, 19.1M rows). Columns used: hvfhs_license_num, request_datetime, PULocationID,
  trip_miles, trip_time, base_passenger_fare. **Read row group by row group** (full load OOMs in 4 GB);
  see `ml/check_signal_nyc.py` for the pattern.
- **Rejected:** Boston Kaggle set (no time signal) — reasons in `reports/signal_check.md`.
  `data/events/td_garden_games.csv` is kept only as a record; not used.
- **Events (training):** real Aug 2024 events at NYC venues (MSG, Barclays, Yankee Stadium, Citi Field)
  in `data/events/nyc_events_2024-08.csv` with venue, pickup zone ID, date, start, end, source_url.
- **Ignore** any `ehailing_fake_data.csv` — fake data never enters the repo or the model.
- Raw data in `data/raw/` (gitignored). Malaysian events in `data/events/malaysia_events.csv` with a
  `source_url` for every row.

## Go/no-go (`ml/check_signal.py` → `reports/signal_check.md`)
Compute the price index (price ÷ expected base for distance + product, fitted on the training period) and report:
- how often the index changes by ≥10% within 15–60 minutes
- variance explained by hour × weekday (and by area, for analysis only)
- lag autocorrelation
- Venue-zone index on event nights vs same hours on non-event nights (effect size + number of games)
Result: Boston NO-GO, NYC GO (modest) — see `reports/signal_check.md`.

## Targets & features
- Targets: `ratio_h = idx_t+h / idx_t` for h ∈ {15, 30, 45, 60}; `drop10_30`.
- Features (information at time t only): hour, minute bucket, weekday, weekend flag, weather (rain,
  temperature, humidity), event features (`event_nearby`, `minutes_to_start`, `minutes_since_end`).
- Variant **with-level** adds current level `idx_t` (served only when the user gives a usual price).
- **No area IDs in the served model** (they don't transfer to Malaysia).

## Splits & leakage
- Time-based split only (e.g. ~70/15/15 by day). No shuffling.
- Base-price regression, encoders and scalers fitted on the training period only.
- No centered rolling windows, future weather or target-derived features.

## Evaluation (`ml/evaluate.py` → `reports/metrics.md`)
On the test period with actual future prices:
1. **Policy savings:** follow advice vs **book now** vs **hour-of-day average ratio**; mean saving in
   index points and % of cases where waiting cost more.
2. **P(drop) quality:** ROC-AUC, precision/recall at the chosen threshold (tuned on validation), calibration.
3. **Forecast error:** MAE of ratio vs persistence (ratio = 1).
Report both variants. If we don't beat the baselines, say so plainly.

## Event effect (`ml/event_effect.py` → `reports/event_effect.md`)
Fit the event features on training event nights; test on held-out event nights. Report effect size with
an interval and the number of games. Mark **VALIDATED** only if the effect holds on held-out events;
otherwise **NOT VALIDATED** — the API then returns `learned_effect: null`.

## Evidence rule
No invented fares, multipliers, base prices for Malaysian apps, or event uplifts anywhere. Every number
in reports must be computed by these scripts.
