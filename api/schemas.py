"""Pydantic models for the API contract in CLAUDE.md (shared with the frontend)."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

App = Literal["grab", "indrive", "gvride"]


class LatLon(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class Quote(BaseModel):
    app: App
    price_rm: float = Field(gt=0, description="Price the user typed from their own app")


class ForecastRequest(BaseModel):
    datetime: datetime
    rain: bool = False
    pickup: LatLon | None = None
    quotes: list[Quote] = []
    usual_price_rm: float | None = Field(default=None, gt=0)
    dropoff: LatLon | None = None  # with pickup: route-based usual-price estimate (only if fare check passed)
    # predicted trip minutes if leaving now / in 15 / 30 / 45 / 60 min (e.g. a traffic prediction sent by
    # the frontend); keys are minutes from now. Used for traffic warnings, not for the price odds.
    traffic_min: dict[int, float] | None = None


class HorizonPoint(BaseModel):
    minutes: int
    pct_change: float
    pct_low: float
    pct_high: float
    p_drop10: float
    expected_rm: dict[str, float] = {}


class LearnedEffect(BaseModel):
    pct: float
    window: str


class ForecastEvent(BaseModel):
    name: str
    source_url: str
    learned_effect: LearnedEffect | None = None
    km: float | None = None        # distance from the pickup
    level: str | None = None       # "right_here" (<= 1 km) | "in_area" (<= 5 km)


class WaitOdds(BaseModel):
    """Headline: chance that waiting `minutes` gets a price >= 10% lower than now."""
    minutes: int
    p_save10: float
    typical_p_save10: float          # same chance across all training windows (base rate)
    pct_low: float                   # p10..p90 range of the price change at `minutes`
    pct_high: float
    rm_range: dict[str, list[float]] = {}  # per quoted app: [low, high] RM at `minutes`


class UsualPriceEstimate(BaseModel):
    rm: float
    km: float
    min: float
    source: str


class TrafficInfo(BaseModel):
    source: str
    minutes: dict[int, float]
    jam_ahead: bool          # some departure in the next 60 min is >= 25% longer than leaving now
    flipped_to_book_now: bool
    km: float | None = None  # route length for leaving now (TomTom), shown on the map with minutes[0]


class ForecastResponse(BaseModel):
    datetime: datetime
    horizon: list[HorizonPoint]
    wait_odds: WaitOdds
    decision: Literal["book_now", "wait"]
    best_time: datetime
    wait_minutes: int
    expected_saving_rm: dict[str, float] = {}
    risk_if_wait_rm: dict[str, float] = {}
    apps_ranked_now: list[str] = []
    apps_ranked_best_time: list[str] = []
    events: list[ForecastEvent] = []
    reasons: list[str]
    model_version: str
    usual_price_estimate: UsualPriceEstimate | None = None  # null unless reports/fare_check.json passed
    traffic: TrafficInfo | None = None  # only when the request carried traffic_min
    # rule-based labels on the outputs above (no new numbers): what kind of moment this is, and how urgent
    situation: Literal["jam_coming", "event_exit", "surge", "pricey", "rush_hour", "normal"] = "normal"
    urgency: Literal["urgent", "wait", "no_gain"] = "no_gain"
    evidence: dict[str, str]


class Event(BaseModel):
    id: str
    name: str
    venue: str
    lat: float
    lon: float
    start: datetime
    end: datetime | None = None  # null when no source publishes an end time
    source_url: str
