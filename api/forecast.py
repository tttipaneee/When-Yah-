"""Forecast -> decision, using the LightGBM models in ml/models/lgbm_v1.joblib (see reports/metrics.md).

Flow: features for (local time, rain, nearby real event) -> with_level model if the user gave a usual
price (level = median quote / usual price), else no_level -> ratio at +15/30/45/60 with p10-p90 band and
P(drop >= 10%) -> applied to each typed quote. RM values are only ever typed quote x predicted ratio.
Malaysian events are listed with their sources but never get a number (learned_effect null) and are not
fed to the model: the validated effect in reports/event_effect.md is for NYC baseball at one venue only. If the model file is missing the API answers 503 (no placeholder numbers).
"""
from datetime import timedelta
import json
from functools import lru_cache
from zoneinfo import ZoneInfo
from pathlib import Path
from statistics import median

import joblib
from fastapi import HTTPException

from api.events import events_near
from api.fare import estimate as fare_estimate
from api.traffic import predicted_minutes
from api.schemas import ForecastEvent, ForecastRequest, ForecastResponse, HorizonPoint, TrafficInfo, WaitOdds
from ml.features import LEVEL_RANGE, serve_row
from ml.train import drop_prob

ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = ROOT / "ml" / "models" / "lgbm_v1.joblib"
EFFECT_SUMMARY = ROOT / "reports" / "event_effect.json"
HORIZONS = (15, 30, 45, 60)


@lru_cache(maxsize=1)
def load_bundle() -> dict | None:
    return joblib.load(MODEL_PATH) if MODEL_PATH.exists() else None


def event_effect() -> dict | None:
    """{'pct', 'window'} if reports/event_effect.md validated the effect on held-out events, else None."""
    if not EFFECT_SUMMARY.exists():
        return None
    d = json.loads(EFFECT_SUMMARY.read_text(encoding="utf-8"))
    return d if d.get("status") == "VALIDATED" and d.get("pct") is not None else None


def event_effect_validated() -> bool:
    return event_effect() is not None


DECISION = ROOT / "reports" / "decision.json"


def decision_rule() -> dict:
    """Written by ml/evaluate.py: per variant, did the "Tunggu" rule beat book-now on held-out test days?"""
    if not DECISION.exists():
        return {}
    return json.loads(DECISION.read_text(encoding="utf-8"))


def _rank(prices: dict[str, float]) -> list[str]:
    return sorted(prices, key=lambda a: prices[a])


def _predict(req: ForecastRequest, quotes: dict[str, float], event) -> tuple[dict, str, float | None]:
    """-> ({minutes: (pct, lo, hi, p_drop)}, variant, level)."""
    b = load_bundle()
    level = None
    if req.usual_price_rm and quotes:
        level = median(quotes.values()) / req.usual_price_rm
    variant = "with_level" if level is not None else "no_level"
    use_event = False  # event features never served for Malaysian events (re-audit: untested transfer)
    X = serve_row(req.datetime, req.rain, event.start if use_event else None,
                  event.end if use_event else None, level)[b["features"][variant]]
    out = {}
    for h in HORIZONS:
        m = b["models"][variant][h]
        mean, lo, hi = (float(m[k].predict(X)[0]) for k in ("mean", "q10", "q90"))
        lo, hi = min(lo, mean), max(hi, mean)
        out[h] = (mean - 1, lo - 1, hi - 1, float(drop_prob(m, X)[0]))
    return out, variant, level


KL = ZoneInfo("Asia/Kuala_Lumpur")
JAM_FACTOR = 1.25  # product rule: a departure >= 25% longer than leaving now counts as "jam coming"


def forecast(req: ForecastRequest) -> ForecastResponse:
    # Rides are in Klang Valley: read the clock in KL time whatever timezone the browser sent
    # (naive times are taken as KL time), so hour/weekday features and event dates are right.
    dt = req.datetime.astimezone(KL) if req.datetime.tzinfo else req.datetime.replace(tzinfo=KL)
    req = req.model_copy(update={"datetime": dt})
    est = None
    if req.pickup and req.dropoff:
        est = fare_estimate((req.pickup.lat, req.pickup.lon), (req.dropoff.lat, req.dropoff.lon))
        if est and req.usual_price_rm is None:  # a typed usual price always wins
            req = req.model_copy(update={"usual_price_rm": est["rm"]})
    quotes = {q.app: q.price_rm for q in req.quotes}  # last quote per app wins
    nearby = events_near(req.datetime, req.pickup.lat if req.pickup else None,
                         req.pickup.lon if req.pickup else None)
    reasons: list[str] = []
    if load_bundle() is None:
        raise HTTPException(503, "model file ml/models/lgbm_v1.joblib missing — run python -m ml.train")
    nearest = min(nearby, key=lambda e: abs((e.start - req.datetime).total_seconds()), default=None)
    pred, variant, level = _predict(req, quotes, nearest)

    pred = {m: tuple(round(v, 4) for v in vals) for m, vals in pred.items()}
    horizon = [HorizonPoint(minutes=m, pct_change=pc, pct_low=lo, pct_high=hi, p_drop10=round(p, 3),
                            expected_rm={a: round(rm * (1 + pc), 2) for a, rm in quotes.items()})
               for m, (pc, lo, hi, p) in pred.items()]
    h30 = next(h for h in horizon if h.minutes == 30)
    typical = load_bundle()["base_rate"][30]
    odds = WaitOdds(minutes=30, p_save10=h30.p_drop10, typical_p_save10=round(typical, 2),
                    pct_low=h30.pct_low, pct_high=h30.pct_high,
                    rm_range={a: [round(rm * (1 + h30.pct_low), 2), round(rm * (1 + h30.pct_high), 2)]
                              for a, rm in quotes.items()})
    # "Tunggu" rule (reports/decision.json): wait for the 15-60 min horizon with the best odds multiple
    # (P(drop >= 10%) / usual chance) if it is >= k — only if that rule beat "book now" on held-out days.
    gate = decision_rule().get("variants", {}).get(variant, {})
    k = load_bundle().get("wait_k", {}).get(variant)
    base = load_bundle()["base_rate"]
    mults = {h.minutes: h.p_drop10 / base[h.minutes] for h in horizon}
    best = max(horizon, key=lambda h: mults[h.minutes])
    odds_high = k is not None and mults[best.minutes] >= k
    wait = bool(gate.get("validated")) and odds_high
    # Potential traffic: predicted trip time per departure (TomTom via api/traffic.py, or sent by the app). Not a price input —
    # traffic did not improve price prediction (reports/traffic_experiment.md) — but a longer trip is a real cost:
    # if waiting puts the trip in much heavier traffic, don't advise waiting.
    traffic, traffic_reason = None, None
    src = "traffic prediction sent by the app"
    raw_tm = req.traffic_min
    if raw_tm is None and req.pickup and req.dropoff:
        raw_tm = predicted_minutes((req.pickup.lat, req.pickup.lon), (req.dropoff.lat, req.dropoff.lon), req.datetime)
        src = "TomTom traffic prediction"
    tm = {int(k_): float(v_) for k_, v_ in (raw_tm or {}).items() if v_ and v_ > 0}
    if 0 in tm and len(tm) > 1:
        now_min = tm[0]
        worst = max((m for m in tm if m > 0), key=lambda m: tm[m])
        jam = tm[worst] >= JAM_FACTOR * now_min
        flipped = False
        at = lambda m: (req.datetime + timedelta(minutes=m)).strftime("%H:%M")
        if wait and tm.get(best.minutes, 0) >= JAM_FACTOR * now_min:
            wait, flipped = False, True
            traffic_reason = (f"Book now — jam coming: trip {now_min:.0f} min if you leave now vs "
                              f"{tm[best.minutes]:.0f} min at {at(best.minutes)} ({src})")
        elif jam:
            traffic_reason = (f"Traffic predicted to build: trip {now_min:.0f} min now, {tm[worst]:.0f} min if you "
                              f"leave at {at(worst)} ({src})")
        elif wait and best.minutes in tm:
            traffic_reason = (f"Traffic: trip {now_min:.0f} min now, {tm[best.minutes]:.0f} min at "
                              f"{at(best.minutes)} ({src})")
        traffic = TrafficInfo(source=src, minutes=tm, jam_ahead=jam,
                              flipped_to_book_now=flipped)
    wait_minutes = best.minutes if wait else 0
    saving, risk = {}, {}
    if wait:
        saving = {a: round(rm * max(-best.pct_change, 0), 2) for a, rm in quotes.items()}
        risk = {a: round(rm * max(best.pct_high, 0), 2) for a, rm in quotes.items()}
    at_best = best.expected_rm if wait else quotes

    reasons.append(f"Chance that waiting 30 min saves you 10% or more: {odds.p_save10:.0%} "
                   f"(usual: {odds.typical_p_save10:.0%}); price in 30 min likely between "
                   f"{odds.pct_low:+.0%} and {odds.pct_high:+.0%}")
    if variant == "with_level":
        clipped = " (clipped to the training range)" if not LEVEL_RANGE[0] <= level <= LEVEL_RANGE[1] else ""
        reasons.append(f"Your quote is {level - 1:+.0%} vs your usual price{clipped}")
        if level >= 1.2:  # "Kenapa mahal?" — see reports/traffic_experiment.md
            reasons.append(f"Kenapa mahal? Your price is {level:.1f}x your usual. Time of day, weather and traffic "
                           "explain very little of a high price in our tests; the rest is demand and driver "
                           "numbers that only the app can see")
    elif variant == "no_level":
        reasons.append("No usual price given: the model can't tell if this price is already high, "
                       "so it only advises waiting when time-of-day patterns are clear")
    if wait:
        surge = level is not None and level >= 1.5 and gate.get("level_ge_1_5")
        ev = (f"in NYC tests, when prices were ≥ 1.5x normal they usually fell back (waiting saved "
              f"~{gate['level_ge_1_5']['saving']:.0%} on average; a simple time-of-day rule did as well)"
              if surge else f"in NYC tests, when this rule said wait it saved {gate['saving_when_wait']:.1%} "
              "on average (a simple time-of-day rule saved slightly more overall)")
        reasons.append(f"Tunggu {best.minutes} min: odds of a ≥10% drop are {mults[best.minutes]:.1f}x the usual; "
                       f"{ev}; {(gate['level_ge_1_5'] if surge else gate)['waits_cost_more']:.0%} of waits cost more")
    elif odds_high and traffic is not None and traffic.flipped_to_book_now:
        pass  # the traffic reason explains the book-now
    elif odds_high:
        reasons.append("Odds of a drop are above usual, but the waiting rule is not validated — book now")
    else:
        rise = max(horizon, key=lambda h: h.pct_change)
        if rise.pct_change >= 0.015:  # model expects the price to edge up (e.g. toward the evening peak)
            reasons.append(f"Book now: the model expects the price to edge up by +{rise.minutes} min "
                           f"({rise.pct_change:+.0%}, likely {rise.pct_low:+.0%} to {rise.pct_high:+.0%}) — "
                           "a time-of-day pattern learned from NYC data; it can't see live KL traffic")
        else:
            reasons.append("Odds of a drop are not clearly above usual — book now")
    if traffic_reason:
        reasons.append(traffic_reason)
    reasons.append("rain" if req.rain else "no rain")
    # Re-audit: the validated effect is NYC baseball at one venue; it is never applied to Malaysian events
    eff = event_effect()
    events = [ForecastEvent(name=e.name, source_url=e.source_url, learned_effect=None) for e in nearby]
    ev_reasons = [f"Event nearby: {e.name}" + (" — in New York data, prices near a baseball stadium rose right "
                                              "after games; not measured for Malaysian events" if eff else
                                              " (effect on price not validated)") for e in nearby]
    reasons += ev_reasons
    reasons.append("Model learned from NYC Uber/Lyft trips (Aug 2024), applied to your local time")
    return ForecastResponse(
        datetime=req.datetime, horizon=horizon, wait_odds=odds, decision="wait" if wait else "book_now",
        best_time=req.datetime + timedelta(minutes=wait_minutes), wait_minutes=wait_minutes,
        expected_saving_rm=saving, risk_if_wait_rm=risk,
        apps_ranked_now=_rank(quotes), apps_ranked_best_time=_rank(at_best),
        events=events, reasons=reasons,
        model_version=f"lgbm_v1/{variant}",
        usual_price_estimate=est, traffic=traffic,
        evidence={"metrics": "reports/metrics.md", "event_effect": "reports/event_effect.md"},
    )
