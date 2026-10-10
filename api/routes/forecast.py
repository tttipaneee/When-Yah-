from fastapi import APIRouter

from api.forecast import forecast
from api.schemas import ForecastRequest, ForecastResponse

router = APIRouter()


@router.post("/api/forecast", response_model=ForecastResponse)
def post_forecast(req: ForecastRequest) -> ForecastResponse:
    return forecast(req)
