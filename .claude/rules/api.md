---
paths:
  - "api/**"
  - "scripts/**"
---

# Backend rules — When Yah?

- FastAPI in `api/main.py`; routers in `api/routes/`; response models match the contract in `CLAUDE.md`.
- Until the model passes evaluation, `/api/forecast` returns a **stub** with the exact contract shape
  (values clearly fake, `model_version: "stub"`), so the frontend is never blocked.
- Forecast flow: features for (datetime, rain, nearby real events) → if `usual_price_rm` given, current
  level = quote ÷ usual price and use the with-level model, else the no-level model → % change at
  +15/30/45/60 with band → apply to **each typed quote** → expected RM per quoted app → decision.
- **Decision:** best_time = horizon with the lowest expected value. Return `wait` only if the expected
  saving exceeds the downside in the high band (from the model's own band); otherwise `book_now`.
  Always return `reasons` from model features or event names.
- **No invented numbers:** no fare tables, no per-app RM without a typed quote, no event uplift unless
  `reports/event_effect.md` is VALIDATED. If the 2× surcharge ceiling is used to clip the band, cite the
  May 2022 Ministry of Transport statement in `reasons`.
- `/api/events` reads `data/events/malaysia_events.csv`; every event returns its `source_url`.
- No outbound calls to ride-hailing services. CORS open to the Vite dev origin only.
- `scripts/run_demo.sh` starts API + web in one command.
