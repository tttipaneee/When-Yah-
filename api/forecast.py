"""Forecast -> decision, using the LightGBM models in ml/models/lgbm_v1.joblib (see reports/metrics.md).

Flow: features for (local time, rain, nearby real event) -> with_level model if the user gave a usual
price (level = median quote / usual price), else no_level -> ratio at +15/30/45/60 with p10-p90 band and
P(drop >= 10%) -> applied to each typed quote. RM values are only ever typed quote x predicted ratio.
Malaysian events are listed with their sources but never get a number (learned_effect null) and are not
fed to the model: the validated effect in reports/event_effect.md is for NYC baseball at one venue only. If the model file is missing the API answers 503 (no placeholder numbers).
"""
from datetime import timedelta
import math
import json
from functools import lru_cache
from zoneinfo import ZoneInfo
from pathlib import Path
from statistics import median

import joblib
from fastapi import HTTPException

from api.events import events_near, haversine_km
from api.fare import estimate as fare_estimate
from api.traffic import predicted_minutes, route_km_now
from api.schemas import (ForecastEvent, ForecastRequest, ForecastResponse, HorizonPoint, LatLon, Outlook, TrafficInfo,
                         WaitOdds, WalkOut)
from ml import model_v2
from ml.features import LEVEL_RANGE, serve_row
from ml.train import MIN_WAIT_P, drop_prob

ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = ROOT / "ml" / "models" / "lgbm_v1.joblib"
EFFECT_SUMMARY = ROOT / "reports" / "event_effect.json"
HORIZONS = (15, 30, 45, 60)


V2_PATH = ROOT / "ml" / "models" / "lgbm_v2.joblib"
V2_VERDICT = ROOT / "reports" / "v2_verdict.json"


@lru_cache(maxsize=1)
def load_bundle() -> dict | None:
    return joblib.load(MODEL_PATH) if MODEL_PATH.exists() else None


@lru_cache(maxsize=1)
def load_v2() -> dict | None:
    """Model v2 (price line + reasons), used per variant only where reports/v2_verdict.json says it beat v1 and
    persistence on test days and September (ml/experiment_v2.py)."""
    if not (V2_PATH.exists() and V2_VERDICT.exists()):
        return None
    verdict = json.loads(V2_VERDICT.read_text(encoding="utf-8")).get("verdict", {})
    b = joblib.load(V2_PATH)
    b["served"] = {v for v, ok in verdict.items() if ok}
    return b if b["served"] else None


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
    """Written by ml/evaluate.py: per variant, did the "wait" rule beat book-now on held-out test days?"""
    if not DECISION.exists():
        return {}
    return json.loads(DECISION.read_text(encoding="utf-8"))


def _walk_out(e, pickup: tuple[float, float], dropoff: tuple[float, float] | None, ended: bool) -> WalkOut:
    """Point just outside the venue's circle: toward the drop-off if it is outside the circle (the walk is on the
    way), else straight away from the venue through the pickup; none if the pickup is at the venue itself."""
    if dropoff and haversine_km(e.lat, e.lon, *dropoff) > HERE_KM:
        towards = dropoff
    elif haversine_km(e.lat, e.lon, *pickup) > 0.05:
        towards = pickup
    else:
        towards = None
    target = walk_km = None
    if towards:
        lat1, lon1, lat2, lon2 = map(math.radians, (e.lat, e.lon, *towards))
        brg = math.atan2(math.sin(lon2 - lon1) * math.cos(lat2),
                         math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1))
        d = WALK_OUT_KM / 6371.0
        tlat = math.asin(math.sin(lat1) * math.cos(d) + math.cos(lat1) * math.sin(d) * math.cos(brg))
        tlon = lon1 + math.atan2(math.sin(brg) * math.sin(d) * math.cos(lat1), math.cos(d) - math.sin(lat1) * math.sin(tlat))
        target = LatLon(lat=round(math.degrees(tlat), 6), lon=round(math.degrees(tlon), 6))
        walk_km = round(haversine_km(*pickup, target.lat, target.lon), 1)
    return WalkOut(event=e.name, venue=e.venue, source_url=e.source_url, end=e.end, ended=ended,
                   center=LatLon(lat=e.lat, lon=e.lon), radius_km=HERE_KM, target=target, walk_km=walk_km)


def _rank(prices: dict[str, float]) -> list[str]:
    return sorted(prices, key=lambda a: prices[a])


def _predict(req: ForecastRequest, quotes: dict[str, float], event) -> tuple[dict, str, float | None, list[str], str, dict]:
    """-> ({minutes: (pct, lo, hi, p_drop)}, variant, level, v2 reasons, line model, {minutes: v1 pct}). P(drop) and
    the v1 pct (used by the validated Wait rule) always from v1; the shown line (pct, lo, hi) from v2 where it passed."""
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
    v1_pct = {h: v[0] for h, v in out.items()}
    v2, because, line = load_v2(), [], "lgbm_v1"
    if v2 and variant in v2["served"]:
        rows = model_v2.serve_rows(serve_row(req.datetime, req.rain, None, None, None), req.datetime,
                                   v2["normal_table"], level)
        for h in HORIZONS:
            m, X2 = v2["models"][variant][h], rows[h][v2["features"][variant]]
            mean, lo, hi = (float(a[0]) for a in model_v2.predict_line(m, X2))
            out[h] = (mean - 1, lo - 1, hi - 1, out[h][3])
            if h == 30:
                because = model_v2.reason_words(model_v2.contributions(m["mean"], X2).iloc[0], X2.iloc[0])
        line = "lgbm_v2"
    return out, variant, level, because, line, v1_pct


KL = ZoneInfo("Asia/Kuala_Lumpur")
HERE_KM = 1.0  # "right here": product choice, roughly the size of the venue's own NYC taxi zone where the effect was measured
WALK_OUT_KM = HERE_KM + 0.2  # walk-out point: product choice, a little past the edge of that circle
JAM_FACTOR = 1.25
RISE_PCT = 0.015  # "edging up": expected rise at some horizon worth a "book now" note (product threshold)
PER_MIN_FACTOR = 1.10  # product rule: mention Grab's per-minute charge when a later trip is >= 10% (and 3 min) longer  # product rule: a departure >= 25% longer than leaving now counts as "jam coming"


def forecast(req: ForecastRequest) -> ForecastResponse:
    # Rides are in Klang Valley: read the clock in KL time whatever timezone the browser sent
    # (naive times are taken as KL time), so hour/weekday features and event dates are right.
    dt = req.datetime.astimezone(KL) if req.datetime.tzinfo else req.datetime.replace(tzinfo=KL)
    req = req.model_copy(update={"datetime": dt})
    est = None
    if req.pickup and req.dropoff:
        est = fare_estimate((req.pickup.lat, req.pickup.lon), (req.dropoff.lat, req.dropoff.lon), req.datetime)
        if est and req.usual_price_rm is None:  # a typed usual price always wins
            req = req.model_copy(update={"usual_price_rm": est["rm"]})
    quotes = {q.app: q.price_rm for q in req.quotes}  # last quote per app wins
    nearby = events_near(req.datetime, req.pickup.lat if req.pickup else None,
                         req.pickup.lon if req.pickup else None)
    reasons: list[str] = []
    if load_bundle() is None:
        raise HTTPException(503, "model file ml/models/lgbm_v1.joblib missing — run python -m ml.train")
    nearest = min(nearby, key=lambda e: abs((e.start - req.datetime).total_seconds()), default=None)
    pred, variant, level, because, line_model, v1_pct = _predict(req, quotes, nearest)

    raw_p = {m: vals[3] for m, vals in pred.items()}  # unrounded P(drop) for the 20% minimum (same as ml.train.tunggu)
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
    outlook = Outlook(minutes=30, pct_change=h30.pct_change, pct_low=h30.pct_low, pct_high=h30.pct_high,
                      because=because, model=line_model)
    # "Wait" rule (reports/decision.json): wait for the 15-60 min horizon with the best odds multiple
    # (P(drop >= 10%) / usual chance) if it is >= k and P(drop >= 10%) there >= MIN_WAIT_P (20%, product rule)
    # — only if that rule beat "book now" on held-out days.
    gate = decision_rule().get("variants", {}).get(variant, {})
    k = load_bundle().get("wait_k", {}).get(variant)
    base = load_bundle()["base_rate"]
    mults = {m: raw_p[m] / base[m] for m in raw_p}
    best = max(horizon, key=lambda h: mults[h.minutes])
    odds_high = k is not None and mults[best.minutes] >= k and raw_p[best.minutes] >= MIN_WAIT_P
    # product rule (10 Oct, same as ml/train.tunggu): never "Wait" while the expected price there is not below now
    falling = v1_pct[best.minutes] < 0  # v1's line: the rule exactly as validated (reports/decision.json)
    wait = bool(gate.get("validated")) and odds_high and falling
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
            traffic_reason = (f"Book now — jam coming: trip {now_min:.0f} min if you leave at {at(0)} vs "
                              f"{tm[best.minutes]:.0f} min at {at(best.minutes)} ({src})")
        elif jam:
            traffic_reason = (f"Traffic predicted to build: trip {now_min:.0f} min at {at(0)}, {tm[worst]:.0f} min if you "
                              f"leave at {at(worst)} ({src})")
        else:  # no jam: show the trip times as information
            m_ = best.minutes if (wait and best.minutes in tm) else max(tm)
            traffic_reason = (f"Traffic: trip {now_min:.0f} min if you leave at {at(0)}, {tm[m_]:.0f} min at "
                              f"{at(m_)} ({src}) — no jam predicted")
        # Grab's fare includes a per-minute charge (Grab Klang Valley fare change, Jan 2023 — carz.com.my /
        # Malay Mail), so a clearly slower trip later likely costs more. Words only: no RM figure (the published
        # rates did not match real quotes well, reports/fare_check.md).
        if "grab" in quotes and tm[worst] >= max(PER_MIN_FACTOR * now_min, now_min + 3):
            traffic_reason += (f". Leaving at {at(worst)} takes {tm[worst] - now_min:.0f} min longer, and Grab's fare "
                               "includes a per-minute charge (Grab fare structure, Jan 2023), so the later trip "
                               "likely costs more")
        km_now = (route_km_now((req.pickup.lat, req.pickup.lon), (req.dropoff.lat, req.dropoff.lon), req.datetime)
                  if req.traffic_min is None and req.pickup and req.dropoff else None)
        traffic = TrafficInfo(source=src, minutes=tm, jam_ahead=jam,
                              flipped_to_book_now=flipped, km=km_now)
    wait_minutes = best.minutes if wait else 0
    saving, risk = {}, {}
    if wait:
        saving = {a: round(rm * max(-best.pct_change, 0), 2) for a, rm in quotes.items()}
        risk = {a: round(rm * max(best.pct_high, 0), 2) for a, rm in quotes.items()}
    at_best = best.expected_rm if wait else quotes
    rise = max(horizon, key=lambda h: h.pct_change)

    reasons.append(f"Chance that waiting 30 min saves you 10% or more: {odds.p_save10:.0%} "
                   f"(usual: {odds.typical_p_save10:.0%}); price in 30 min likely between "
                   f"{odds.pct_low:+.0%} and {odds.pct_high:+.0%}")
    if because:  # one-line prediction from model v2 (reports/metrics_v2.md)
        size = "about the same" if abs(h30.pct_change) < 0.005 else f"likely {h30.pct_change:+.0%}"
        reasons.append(f"Price in 30 min: {size} ({h30.pct_low:+.0%} to {h30.pct_high:+.0%}), "
                       f"mainly because {' and '.join(because)} (main reasons in the model)")
    if variant == "with_level":
        clipped = " (clipped to the training range)" if not LEVEL_RANGE[0] <= level <= LEVEL_RANGE[1] else ""
        reasons.append(f"Your quote is {level - 1:+.0%} vs your usual price{clipped}")
        if level >= 1.2:  # "Why so pricey?" — see reports/traffic_experiment.md
            reasons.append(f"Why so pricey? Your price is {level:.1f}x your usual. Time of day, weather and traffic "
                           "explain very little of a high price in our tests; the rest is demand and driver "
                           "numbers that only the app can see")
    elif variant == "no_level":
        reasons.append("No usual price given: the model can't tell if this price is already high, "
                       "so it only advises waiting when time-of-day patterns are clear")
    if wait:
        surge = level is not None and level >= 1.5 and gate.get("level_ge_1_5")
        ev = (f"in our tests on real ride data, when prices were ≥ 1.5x normal they usually fell back (waiting saved "
              f"~{gate['level_ge_1_5']['saving']:.0%} on average; a simple time-of-day rule did as well or better)"
              if surge else f"in our tests on real ride data, when this rule said wait it saved {gate['saving_when_wait']:.1%} "
              "on average (a simple time-of-day rule saved slightly more overall)")
        reasons.append(f"Wait {best.minutes} min: {best.p_drop10:.0%} chance of a ≥10% drop by then "
                       f"({mults[best.minutes]:.1f}x the usual); "
                       f"{ev}; {(gate['level_ge_1_5'] if surge else gate)['waits_cost_more']:.0%} of waits cost more")
    elif odds_high and traffic is not None and traffic.flipped_to_book_now:
        pass  # the traffic reason explains the book-now
    elif odds_high and not falling:
        reasons.append(f"Book now: the chance of a ≥10% drop by +{best.minutes} min is {best.p_drop10:.0%}, but the "
                       f"Wait rule's expected price then is {v1_pct[best.minutes]:+.0%} — not lower than now (product rule; "
                       "not tested on held-out days)")
    elif odds_high:
        reasons.append("Odds of a drop are above usual, but the waiting rule is not validated — book now")
    else:
        if rise.pct_change >= RISE_PCT:  # model expects the price to edge up (e.g. toward the evening peak)
            reasons.append(f"Book now: the model expects the price to edge up by +{rise.minutes} min "
                           f"({rise.pct_change:+.0%}, likely {rise.pct_low:+.0%} to {rise.pct_high:+.0%}) — "
                           "a time-of-day pattern from our training data"
                           + ("" if traffic is not None else "; it can't see live traffic"))
        else:
            reasons.append(f"Book now: chance of a ≥10% drop is {best.p_drop10:.0%} at best (+{best.minutes} min), "
                           f"under our {MIN_WAIT_P:.0%} minimum to advise waiting")
    if traffic_reason:
        reasons.append(traffic_reason)
    reasons.append("rain" if req.rain else "no rain")
    # Re-audit: the validated effect is NYC baseball at one venue; it is never applied to Malaysian events
    eff = event_effect()
    pk = (req.pickup.lat, req.pickup.lon) if req.pickup else None
    events, ev_reasons, exit_soon, exit_now, walk = [], [], False, False, None
    for e in nearby:
        km = round(haversine_km(pk[0], pk[1], e.lat, e.lon), 1) if pk else None
        lvl = None if km is None else ("right_here" if km <= HERE_KM else "in_area")
        events.append(ForecastEvent(name=e.name, source_url=e.source_url, learned_effect=None, km=km, level=lvl))
        where = (f"Event right here ({km:.1f} km)" if lvl == "right_here" else
                 f"Event in the area ({km:.1f} km)" if lvl else "Event today")
        # Exit hint (words only, no %): validated window is 0-45 min after the end (reports/event_effect.md);
        # shown from 30 min before a published end, for pickups right here
        # (own prefix so the web app, which redraws the "Event right here" rows itself, still shows it)
        to_end = (e.end - req.datetime).total_seconds() / 60 if e.end else None
        if eff and lvl == "right_here" and to_end is not None and -45 <= to_end <= 30:
            exit_soon, exit_now = exit_soon or to_end > 0, True
            if walk is None:
                walk = _walk_out(e, pk, (req.dropoff.lat, req.dropoff.lon) if req.dropoff else None, to_end <= 0)
            ev_reasons.append(
                f"Event ending right here: {e.name} " + (f"ends at {e.end:%H:%M}" if to_end > 0 else
                                                         f"ended at {e.end:%H:%M}")
                + ". In our ride data, prices right next to a stadium were higher for at least the first ~45 min "
                "after games ended (not yet measured in Malaysia)")
        ev_reasons.append(f"{where}: {e.name}" + (
            " — in our training data, prices within ~1 km of a stadium rose right after games; not measured for "
            "Malaysian events" if (eff and lvl == "right_here") else " (effect on price not measured in Malaysia)"))
    reasons += ev_reasons
    # Situation (first match wins) and urgency: product labels on the outputs above, no new numbers
    rising = rise.pct_change >= RISE_PCT
    situation = ("jam_coming" if traffic is not None and traffic.jam_ahead else
                 "event_exit" if exit_now else
                 "surge" if level is not None and level >= 1.5 else
                 "pricey" if level is not None and level >= 1.2 else
                 "rush_hour" if rising else "normal")
    urgency = ("wait" if wait else
               "urgent" if (traffic is not None and traffic.jam_ahead) or exit_soon or rising else "no_gain")
    return ForecastResponse(
        situation=situation, urgency=urgency, walk_out=walk,
        datetime=req.datetime, horizon=horizon, wait_odds=odds, outlook=outlook, decision="wait" if wait else "book_now",
        best_time=req.datetime + timedelta(minutes=wait_minutes), wait_minutes=wait_minutes,
        expected_saving_rm=saving, risk_if_wait_rm=risk,
        apps_ranked_now=_rank(quotes), apps_ranked_best_time=_rank(at_best),
        events=events, reasons=reasons,
        model_version=f"lgbm_v1/{variant}" + ("+lgbm_v2_line" if line_model == "lgbm_v2" else ""),
        usual_price_estimate=est, traffic=traffic,
        evidence={"metrics": "reports/metrics.md", "event_effect": "reports/event_effect.md",
                  "line": "reports/metrics_v2.md"},
    )
