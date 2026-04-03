"""Recommendation endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.dependencies import get_dashboard_service
from api.schemas import RecommendationEnvelope
from ui.dashboard_service import DashboardService

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.get("/latest", response_model=RecommendationEnvelope)
def latest(symbol: str = "EURUSD", timeframe: str = "M5", service: DashboardService = Depends(get_dashboard_service)) -> RecommendationEnvelope:
    recommendation = service.generate_recommendation(symbol=symbol, timeframe=timeframe)
    return RecommendationEnvelope(recommendation=service.recommendation_to_record(recommendation))
