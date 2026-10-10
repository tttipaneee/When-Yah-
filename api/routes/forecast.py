from fastapi import APIRouter

from api.forecast import forecast
from api.schemas import ForecastRequest, ForecastResponse

router = APIRouter()


@router.post("/api/forecast", response_model=ForecastResponse)
def post_forecast(req: ForecastRequest) -> ForecastResponse:
    return forecast(req)


@router.post("/api/explain")
def post_explain(req: ForecastRequest) -> dict:
    """Plain-language explanation by Claude from this forecast's facts only (api/explain.py); ai=false on any failure."""
    from api.explain import explain
    return explain(req)
