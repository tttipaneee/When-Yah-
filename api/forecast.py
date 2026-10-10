"""Forecast -> decision, using the LightGBM models in ml/models/lgbm_v1.joblib (see reports/metrics.md).

Flow: features for (local time, rain, nearby real event) -> with_level model if the user gave a usual
price (level = median quote / usual price), else no_level -> ratio at +15/30/45/60 with p10-p90 band and
P(drop >= 10%) -> applied to each typed quote. RM values are only ever typed quote x predicted ratio.
Event features are used only when reports/event_effect.md says VALIDATED; otherwise events are listed
without a number. Falls back to a clearly-labelled stub if the model file is missing.
"""
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from statistics import median

import joblib

from api.events import events_near
from api.schemas import ForecastEvent, ForecastRequest, ForecastResponse, HorizonPoint
from ml.features import LEVEL_RANGE, serve_row

ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = ROOT / "ml" / "models" / "lgbm_v1.joblib"
EFFECT_REPORT = ROOT / "reports" / "event_effect.md"
HORIZONS = (15, 30, 45, 60)
_STUB = {15: (-0.06, -0.14, 0.03, 0.41), 30: (-0.08, -0.17, 0.02, 0.45),
         45: (-0.05, -0.15, 0.05, 0.40), 60: (-0.03, -0.13, 0.07, 0.36)}


@lru_cache(maxsize=1)
def load_bundle() -> dict | None:
    return joblib.load(MODEL_PATH) if MODEL_PATH.exists() else None


def event_effect_validated() -> bool:
    return EFFECT_REPORT.exists() and "**Status: VALIDATED**" in EFFECT_REPORT.read_text(encoding="utf-8")


def _rank(prices: dict[str, float]) -> list[str]:
    return sorted(prices, key=lambda a: prices[a])


def _predict(req: ForecastRequest, quotes: dict[str, float], event) -> tuple[dict, str, float | None]:
    """-> ({minutes: (pct, lo, hi, p_drop)}, variant, level)."""
    b = load_bundle()
    level = None
    if req.usual_price_rm and quotes:
        level = median(quotes.values()) / req.usual_price_rm
    variant = "with_level" if level is not None else "no_level"
    use_event = event is not None and event_effect_validated()
    X = serve_row(req.datetime, req.rain, event.start if use_event else None,
                  event.end if use_event else None, level)[b["features"][variant]]
    out = {}
    for h in HORIZONS:
        m = b["models"][variant][h]
        mean, lo, hi = (float(m[k].predict(X)[0]) for k in ("mean", "q10", "q90"))
        lo, hi = min(lo, mean), max(hi, mean)
        out[h] = (mean - 1, lo - 1, hi - 1, float(m["clf"].predict_proba(X)[0, 1]))
    return out, variant, level


def forecast(req: ForecastRequest) -> ForecastResponse:
    quotes = {q.app: q.price_rm for q in req.quotes}  # last quote per app wins
    nearby = events_near(req.datetime, req.pickup.lat if req.pickup else None,
                         req.pickup.lon if req.pickup else None)
    reasons: list[str] = []
    if load_bundle() is None:
        pred, variant, level = _STUB, "stub", None
        reasons.append("STUB forecast: model file missing, placeholder numbers — not a prediction")
    else:
        nearest = min(nearby, key=lambda e: abs((e.start - req.datetime).total_seconds()), default=None)
        pred, variant, level = _predict(req, quotes, nearest)

    pred = {m: tuple(round(v, 4) for v in vals) for m, vals in pred.items()}
    horizon = [HorizonPoint(minutes=m, pct_change=pc, pct_low=lo, pct_high=hi, p_drop10=round(p, 3),
                            expected_rm={a: round(rm * (1 + pc), 2) for a, rm in quotes.items()})
               for m, (pc, lo, hi, p) in pred.items()]
    best = min(horizon, key=lambda h: h.pct_change)
    # wait only if the expected saving beats the downside in the model's p90 band
    wait = best.pct_change < 0 and -best.pct_change > max(best.pct_high, 0)
    wait_minutes = best.minutes if wait else 0
    saving, risk = {}, {}
    if wait:
        saving = {a: round(rm * -best.pct_change, 2) for a, rm in quotes.items()}
        risk = {a: round(rm * max(best.pct_high, 0), 2) for a, rm in quotes.items()}
    at_best = best.expected_rm if wait else quotes

    if variant == "with_level":
        clipped = " (clipped to the training range)" if not LEVEL_RANGE[0] <= level <= LEVEL_RANGE[1] else ""
        tail = " — prices this far above normal tended to fall back in the training data" if level > 1.1 else ""
        reasons.append(f"Your quote is {level - 1:+.0%} vs your usual price{clipped}{tail}")
    elif variant == "no_level":
        reasons.append("No usual price given: the model can't tell if this price is already high, "
                       "so it only advises waiting when time-of-day patterns are clear")
    if wait:
        reasons.append(f"Lowest expected price at +{best.minutes} min ({best.pct_change:+.0%}, "
                       f"range {best.pct_low:+.0%} to {best.pct_high:+.0%})")
    else:
        reasons.append(f"Expected saving from waiting does not beat the risk of a rise "
                       f"(up to {best.pct_high:+.0%} at +{best.minutes} min)")
    reasons.append("rain" if req.rain else "no rain")
    validated = event_effect_validated()
    events = [ForecastEvent(name=e.name, source_url=e.source_url, learned_effect=None) for e in nearby]
    reasons += [f"Event nearby: {e.name}" + ("" if validated else " (effect on price not validated)")
                for e in nearby]
    if variant != "stub":
        reasons.append("Model learned from NYC Uber/Lyft trips (Aug 2024), applied to your local time")
    return ForecastResponse(
        datetime=req.datetime, horizon=horizon, decision="wait" if wait else "book_now",
        best_time=req.datetime + timedelta(minutes=wait_minutes), wait_minutes=wait_minutes,
        expected_saving_rm=saving, risk_if_wait_rm=risk,
        apps_ranked_now=_rank(quotes), apps_ranked_best_time=_rank(at_best),
        events=events, reasons=reasons,
        model_version=f"lgbm_v1/{variant}" if variant != "stub" else "stub",
        evidence={"metrics": "reports/metrics.md", "event_effect": "reports/event_effect.md"},
    )
