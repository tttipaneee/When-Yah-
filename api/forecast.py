"""Forecast -> decision. STUB until the real model passes evaluation (CLAUDE.md rule 6).

The stub's percentages are placeholders, not model output; model_version="stub" and the first
reason say so. RM values are only ever the user's typed quote x (1 + pct_change).
"""
from datetime import timedelta

from api.events import events_near
from api.schemas import ForecastEvent, ForecastRequest, ForecastResponse, HorizonPoint

HORIZONS = (15, 30, 45, 60)
# Placeholder shape for frontend development only (not a prediction).
_STUB = {15: (-0.06, -0.14, 0.03, 0.41), 30: (-0.08, -0.17, 0.02, 0.45),
         45: (-0.05, -0.15, 0.05, 0.40), 60: (-0.03, -0.13, 0.07, 0.36)}


def _rank(prices: dict[str, float]) -> list[str]:
    return sorted(prices, key=lambda a: prices[a])


def forecast(req: ForecastRequest) -> ForecastResponse:
    quotes = {q.app: q.price_rm for q in req.quotes}  # last quote per app wins
    horizon = [
        HorizonPoint(minutes=m, pct_change=pc, pct_low=lo, pct_high=hi, p_drop10=p,
                     expected_rm={a: round(rm * (1 + pc), 2) for a, rm in quotes.items()})
        for m, (pc, lo, hi, p) in _STUB.items()
    ]
    best = min(horizon, key=lambda h: h.pct_change)
    # wait only if the expected saving beats the downside in the high band
    wait = best.pct_change < 0 and -best.pct_change > max(best.pct_high, 0)
    wait_minutes = best.minutes if wait else 0
    saving, risk = {}, {}
    if wait:
        saving = {a: round(rm * -best.pct_change, 2) for a, rm in quotes.items()}
        risk = {a: round(rm * max(best.pct_high, 0), 2) for a, rm in quotes.items()}
    at_best = best.expected_rm if wait else quotes
    events = [ForecastEvent(name=e.name, source_url=e.source_url, learned_effect=None)
              for e in events_near(req.datetime, req.pickup.lat if req.pickup else None,
                                   req.pickup.lon if req.pickup else None)]
    reasons = ["STUB forecast: placeholder numbers for frontend development, not a model prediction",
               "rain" if req.rain else "no rain"]
    reasons += [f"event nearby: {e.name}" for e in events]
    return ForecastResponse(
        datetime=req.datetime, horizon=horizon, decision="wait" if wait else "book_now",
        best_time=req.datetime + timedelta(minutes=wait_minutes), wait_minutes=wait_minutes,
        expected_saving_rm=saving, risk_if_wait_rm=risk,
        apps_ranked_now=_rank(quotes), apps_ranked_best_time=_rank(at_best),
        events=events, reasons=reasons, model_version="stub",
        evidence={"metrics": "reports/metrics.md"},
    )
