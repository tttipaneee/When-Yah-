"""Plain-language explanation of one forecast by Claude, held to the evidence rule.

The server recomputes the forecast (never trusts numbers sent by the browser), gives Claude only those facts,
and rejects any answer that contains a number not present in the facts. On rejection, a missing
ANTHROPIC_API_KEY, or any API error, the caller gets `ai: false` and the app keeps its normal text.
"""
import json
import os
import re

from api.forecast import forecast
from api.schemas import ForecastRequest

MODEL = "claude-sonnet-5-5"  # cheaper than Opus; enough for 2 plain sentences (Ravin, 10 Oct)
_ENV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
APP_NAME = {"grab": "Grab", "indrive": "inDrive", "gvride": "GV Ride"}

SYSTEM = (
    "You explain a ride-price forecast to a rider in Kuala Lumpur, in plain, friendly English. "
    "Write 2 short sentences (under 40 words in total), no lists, no headings. Say what to do (wait or book now) and why, "
    "using ringgit amounts when they are given. "
    "Use only the numbers that appear in the facts, written the same way; never compute, round or invent a number. "
    "Do not mention models, AUC, data sets, cities other than Kuala Lumpur, or how the forecast was made. "
    "We are not connected to Grab, inDrive or GV Ride; never suggest we are. "
    "It is a forecast, not a promise: say so briefly. "
    "For events, say only what the reasons say: an event nearby is information, and its effect on price in "
    "Malaysia is not measured, so never say an event will or could push prices up unless a reason says so."
)


def _api_key() -> str | None:
    if not os.getenv("ANTHROPIC_API_KEY") and os.path.exists(_ENV):
        for line in open(_ENV, encoding="utf-8"):
            if line.strip().startswith("ANTHROPIC_API_KEY="):
                os.environ["ANTHROPIC_API_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.getenv("ANTHROPIC_API_KEY") or None


def _rm(v: float) -> str:
    return f"RM{v:.2f}"


def facts(req: ForecastRequest) -> dict:
    """The only facts Claude may use: decision, odds and ranges, RM for typed quotes, reasons, events."""
    r = forecast(req)
    quotes = {q.app: q.price_rm for q in req.quotes}
    o = r.wait_odds
    f = {
        "advice": f"Wait {r.wait_minutes} min" if r.decision == "wait" else "Book now",
        "chance_10pct_cheaper_in_30_min": f"{o.p_save10:.0%}",
        "usual_chance": f"{o.typical_p_save10:.0%}",
        "price_in_30_min_likely_between": f"{o.pct_low:+.0%} and {o.pct_high:+.0%}",
        "situation": r.situation.replace("_", " "), "urgency": r.urgency.replace("_", " "),
        "your_prices": {APP_NAME[a]: _rm(p) for a, p in quotes.items()},
        "likely_price_in_30_min": {APP_NAME[a]: f"{_rm(lo)} to {_rm(hi)}" for a, (lo, hi) in o.rm_range.items()},
        "reasons": [t for t in r.reasons if t not in ("rain", "no rain")],
        "events_nearby": [e.name for e in r.events],
    }
    if req.usual_price_rm:
        f["your_usual_price"] = _rm(req.usual_price_rm)
    if r.decision == "wait":
        h = next(x for x in r.horizon if x.minutes == r.wait_minutes)
        f["expected_after_waiting"] = {APP_NAME[a]: _rm(v) for a, v in h.expected_rm.items()}
        f["chance_10pct_cheaper_by_then"] = f"{h.p_drop10:.0%}"
    if r.traffic is not None:
        f["trip_minutes_if_leaving_now"] = f"{r.traffic.minutes.get(0, 0):.0f}"
    return f


def allowed_numbers(f: dict) -> set[str]:
    nums = set(re.findall(r"\d+(?:\.\d+)?", json.dumps(f, ensure_ascii=False)))
    return nums | {n.lstrip("0") or "0" for n in nums} | {str(float(n)).rstrip("0").rstrip(".") for n in nums}


def unsupported_numbers(text: str, f: dict) -> list[str]:
    ok = allowed_numbers(f)
    return [n for n in re.findall(r"\d+(?:\.\d+)?", text) if n not in ok and n.rstrip("0").rstrip(".") not in ok]


def explain(req: ForecastRequest) -> dict:
    f = facts(req)
    if not _api_key():
        return {"ai": False, "text": None, "reason": "ANTHROPIC_API_KEY not set in .env"}
    import anthropic  # imported here so the API runs without the package when AI is off

    try:
        client = anthropic.Anthropic(timeout=30.0, max_retries=1)
        msg = client.beta.messages.create(
            model=MODEL, max_tokens=1024, system=SYSTEM,
            output_config={"effort": "low"},  # short plain-language text; thinking stays on (can't be disabled)
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            messages=[{"role": "user", "content": "Facts (JSON):\n" + json.dumps(f, ensure_ascii=False, indent=1)
                       + "\n\nExplain this to the rider."}],
        )
    except anthropic.APIConnectionError:
        return {"ai": False, "text": None, "reason": "could not reach the Claude API"}
    except anthropic.APIStatusError as e:
        return {"ai": False, "text": None, "reason": f"Claude API error {e.status_code}"}
    if msg.stop_reason == "refusal":
        return {"ai": False, "text": None, "reason": "declined"}
    text = " ".join(b.text for b in msg.content if b.type == "text").strip()
    bad = unsupported_numbers(text, f)
    if not text or bad:  # evidence rule: no number that isn't in the facts
        return {"ai": False, "text": None, "reason": f"rejected: numbers not in the data ({', '.join(bad[:5])})"}
    return {"ai": True, "text": text, "model": msg.model, "facts": f}
