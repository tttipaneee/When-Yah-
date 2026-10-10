# When Yah? — Product Requirements (Dormathon 2026)

Track 1: Predictive Model — "Predict Early, Decide Better". Team: Ravin (data, model, API) and
Partner (design, frontend, slides, pitch). Build Sat 10 Oct ~12:00 → submit Sun 11 Oct 09:00 MYT (aim 08:30).

## 1. Problem & solution
**Problem.** At peak hours, Klang Valley riders check Grab, inDrive and GV Ride one by one and still
can't tell if the price will drop if they wait. Consumer groups say e-hailing fares and surges are
rising without transparency (NST letter, 15 Feb 2026). Comparison apps exist overseas (Obi, Hackney,
Bellhop) but not for Malaysian apps, and none clearly says *when* to book.

**Solution.** The user types the price(s) they see. We predict how that price will change over the next
60 minutes and turn it into a decision: book now or wait until X, which of their quoted apps is likely
cheapest at that time, and whether a real event nearby is likely to push prices up.

**Proof.** On held-out real ride data, following our advice saves more than "always book now" and
"hour-of-day average" baselines (`reports/metrics.md`).

**Evidence rule.** Every number traces to real data or a cited, dated source. No invented fares,
multipliers or per-app prices (see `CLAUDE.md`).

**Out of scope.** Live connection to ride-hailing apps, scraping, simulated prices, accounts, payments,
background location tracking, avatar (later), live Google traffic.

## 2. Tech stack
| Layer | Choice |
|---|---|
| Data/ML | Python 3.11, pandas, pyarrow, scikit-learn, LightGBM, joblib |
| Primary data | NYC TLC High Volume FHV trip records, Aug 2024 (`fhvhv_tripdata_2024-08.parquet`, 19.1M trips): request time, pickup zone, miles, minutes, base passenger fare, company (HV0003 Uber, HV0005 Lyft). Boston Kaggle set rejected at go/no-go (no time signal) — `reports/signal_check.md` |
| Event data (training) | Real Aug 2024 events at NYC venues (Madison Square Garden, Barclays Center, Yankee Stadium, Citi Field) with source URLs → `data/events/nyc_events_2024-08.csv` |
| Backup data | Another NYC HVFHV month (same schema) if more history is needed |
| Event data (Malaysia) | Real upcoming events from official venue/ticketing pages, stored with source URLs in `data/events/malaysia_events.csv` |
| API | FastAPI + uvicorn, Pydantic |
| Frontend | Vite + React + TypeScript; chart lib and styling chosen with Partner's design |
| Location | Browser Geolocation API, one-shot, with permission (nearby events only) |

## 3. Functional requirements
P0 = must work in demo · P1 = should · P2 = only if ahead.

| ID | Requirement | Pri |
|---|---|---|
| FR1 | **"Masukkan harga yang anda nampak":** enter one or more real quotes (app + RM) and date/time | P0 |
| FR2 | **When Yah? forecast:** % change with low/high band at +15/30/45/60 min, P(drop ≥10% within 30 min), decision book_now/wait, best time, countdown; RM values only for quoted apps | P0 |
| FR3 | Ranking of the user's quoted apps now vs at best time | P0 |
| FR4 | Optional **"harga biasa"** (usual price) input that tells the model whether the user is currently in a surge | P1 |
| FR5 | Event radar: real events near the pickup on the chosen date (with source link); learned effect shown only if validated in `reports/event_effect.md` | P0 (list) / P1 (effect) |
| FR6 | Judges' metrics screen: policy savings vs baselines, P(drop) AUC, forecast error vs persistence, event-effect result | P0 (pitch) |
| FR7 | Rain toggle that changes the forecast | P1 |
| FR8 | Presenter route `/demo`: preset scenarios (Fri 18:10 peak, Sat 22:45 near an event, Tue 14:00 quiet) with example quotes clearly marked "example" | P0 |
| FR9 | "Walk out of the zone" tip — only if `reports/event_effect.md` shows lower prices in neighbouring zones on event nights | P2 |
| FR10 | "Use my location" one-shot geolocation for nearby events | P2 |

Non-functional: forecast < 1 s; works offline; no personal data stored.

## 4. Data & model
- **Price index** = price ÷ that ride's expected base price for distance and product, fitted on training data.
- **Targets:** ratio `idx_t+h / idx_t` for h ∈ {15, 30, 45, 60}; `drop10_30` = index falls ≥10% within 30 min.
- **Two model variants:** (a) *no-level* — time, weekday, weather, event features only; (b) *with-level* —
  adds current surge level, used when the user gives a usual price (level = quote ÷ usual price).
- **Event effect:** features `minutes_to_start`, `minutes_since_end`, `event_nearby` from real NYC venue
  events; tested on held-out event nights → `reports/event_effect.md`.
- Details and leakage rules: `.claude/rules/ml.md`.

## 5. Architecture
```
user quote(s) + time + rain (+ usual price) (+ nearby real events)
   → model (trained on real data) → % change at +15..60 with band + P(drop)
   → apply to each real quote → expected RM per quoted app → decision + best time
event list (real, cited) → learned effect added only if validated
```
API contract: see `CLAUDE.md`.

## 6. Frontend
**Design by Partner** (`design/`). Screens (function only): Quote entry (FR1, FR4), When Yah? forecast
(FR2, FR3), Event radar (FR5), Judges' metrics (FR6), Presenter `/demo` (FR8). Every number shows its
source (model metrics, user input, cited event page).

## 7. Milestones — divided by 2
| Time (MYT) | Ravin | Partner |
|---|---|---|
| 12:00–12:30 | Repo setup; download data (Boston, then NYC HVFHV Aug 2024) | Sketch screens |
| 12:30–14:00 | `check_signal_nyc.py` → `reports/signal_check.md` ✅ done: Boston NO-GO, NYC GO (modest) | Designs → `design/`; collect real Malaysian events with source URLs |
| **14:00 go/no-go** | ✅ GO on NYC. Collect real Aug 2024 NYC venue events (MSG, Barclays, Yankee Stadium, Citi Field) with URLs | — |
| 14:00–17:00 | `build_dataset.py`, `features.py`, `train.py` (no-level + with-level), `evaluate.py` with baselines; stub `/api/forecast` | Frontend against stub API: quote entry, forecast chart, countdown, decision |
| 17:00–19:00 | Real `/api/forecast` applying % change to quotes; `/api/events` from the CSV | Wire screens; ranking |
| **19:00 checkpoint** | **End-to-end: typed quote → forecast → "wait 25 min, save RM4"** | |
| 19:00–23:00 | `event_effect.py` validation; usual-price variant; rain; tuning | Event radar; metrics screen; slides v1 |
| 23:00–02:00 | Final metrics; `leakage-auditor`; README; model card | Polish; real numbers in slides; competitor slide |
| 02:00–04:00 | Bug fixes only; **freeze 04:00** | Backup demo video |
| 04:00–06:00 | Naps in turns | Naps in turns |
| 06:00–08:30 | `submission-checker`; final test; submit | Rehearse ×3; final slides |

## 8. Demo script (2 minutes)
1. Open the real Grab app (and inDrive) on stage; type the quotes into "Masukkan harga yang anda nampak".
2. Forecast: chance of a ≥10% drop, best time, countdown, expected saving on *their* quote.
3. Ranking of the quoted apps now vs at best time.
4. Event radar: a real upcoming event (with source) near the pickup; learned effect if validated.
5. Proof slide from `reports/metrics.md`: savings vs "book now" and "hour average" on held-out real data.

## 9. Cut list (in order)
1. FR10 geolocation 2. FR9 walk-out tip 3. FR7 rain toggle 4. FR4 usual price
5. Event effect number (keep the real event list)

## 10. Risks
1. Signal is modest (simple model beats persistence by ~5% MAE at +30 min) → pitch savings honestly; Boston already rejected for no signal.
2. Few events in the data period → event effect may not validate → show events without numbers.
3. Surge is hard to predict (a Chicago project reached ~25% precision) → probabilities and savings vs baselines.
4. US patterns applied to KL → state it plainly; roadmap: users' typed quotes become Malaysian training data.
5. inDrive is bid-based → the typed inDrive price is the rider's offer/accepted fare; treat it as a quote.

## 11. Roadmap slide
Typed quotes become a Malaysian price dataset → model retrained on Malaysian data → screenshot reading
→ official data partnerships (as Obi does in the US) → avatar guide → live traffic.

## 12. References
- Boston Uber/Lyft dataset overview: https://www.analyticsvidhya.com/blog/2021/06/uber-and-lyft-cab-prices-data-analysis-and-visualization/
- Chicago TNP trips: https://catalog.data.gov/dataset/transportation-network-providers-trips-2025
- Surcharge cap statement (May 2022): https://www.thevibes.com/articles/news/61517/e-hailing-operators-can-set-their-own-fares-no-govt-regulation-wee
- Rising e-hailing fares (NST, Feb 2026): https://www.nst.com.my/amp/opinion/letters/2026/02/1378200/four-ways-address-rising-e-hailing-fares
- Obi: https://www.badcredit.org/news/rideshare-comparison-app-obi-can-save-you-money/
- Hackney: https://zeli.app/story/48893550
- Chicago surge prediction project: https://dev.to/datadeverik/uber-surge-predicted-with-machine-learning-chicago-6kl
