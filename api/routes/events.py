from datetime import date

from fastapi import APIRouter

from api.events import events_on
from api.schemas import Event

router = APIRouter()


@router.get("/api/events", response_model=list[Event])
def get_events(date: date) -> list[Event]:
    return events_on(date)
