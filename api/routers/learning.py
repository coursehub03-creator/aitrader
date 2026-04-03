"""Learning center endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.dependencies import get_dashboard_service
from api.schemas import (
    HistoricalFetchRequest,
    HistoricalFetchResponse,
    HistoricalValidationEnvelope,
    HistoricalValidationRequest,
    HistoryInventoryEnvelope,
)
from ui.dashboard_service import DashboardService

router = APIRouter(prefix="/learning", tags=["learning"])


@router.get("/center")
def learning_center(service: DashboardService = Depends(get_dashboard_service)) -> dict:
    payload = service.learning_center_payload()
    payload["events"] = payload.get("events", []).to_dict(orient="records")
    payload["health"] = dict(payload.get("health", {}))
    return payload


@router.post("/history/fetch", response_model=HistoricalFetchResponse)
def fetch_historical_data(
    request: HistoricalFetchRequest,
    service: DashboardService = Depends(get_dashboard_service),
) -> HistoricalFetchResponse:
    payload = service.fetch_historical_data(
        symbol=request.symbol,
        timeframe=request.timeframe,
        lookback_days=request.lookback_days,
    )
    return HistoricalFetchResponse(**payload)


@router.get("/history/inventory", response_model=HistoryInventoryEnvelope)
def history_inventory(
    service: DashboardService = Depends(get_dashboard_service),
) -> HistoryInventoryEnvelope:
    frame = service.historical_data_summary()
    return HistoryInventoryEnvelope(rows=frame.to_dict(orient="records"))


@router.post("/validation/run", response_model=HistoricalValidationEnvelope)
def run_historical_validation(
    request: HistoricalValidationRequest,
    service: DashboardService = Depends(get_dashboard_service),
) -> HistoricalValidationEnvelope:
    if not request.run:
        return HistoricalValidationEnvelope(rows=[])
    frame = service.run_historical_validation()
    return HistoricalValidationEnvelope(rows=frame.to_dict(orient="records"))


@router.get("/validation/results", response_model=HistoricalValidationEnvelope)
def historical_validation_results(
    service: DashboardService = Depends(get_dashboard_service),
) -> HistoricalValidationEnvelope:
    payload = service.learning_center_payload()
    frame = payload.get("historical_validation")
    if isinstance(frame, dict):
        return HistoricalValidationEnvelope(rows=[])
    return HistoricalValidationEnvelope(rows=frame.to_dict(orient="records"))
