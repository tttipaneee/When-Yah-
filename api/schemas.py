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


class ForecastResponse(BaseModel):
    datetime: datetime
    horizon: list[HorizonPoint]
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
    evidence: dict[str, str]


class Event(BaseModel):
    id: str
    name: str
    venue: str
    lat: float
    lon: float
    start: datetime
    end: datetime
    source_url: str
