"""Alert endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.dependencies import get_dashboard_service
from api.schemas import TableEnvelope
from ui.dashboard_service import DashboardService

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("/history", response_model=TableEnvelope)
def alert_history(limit: int = 100, service: DashboardService = Depends(get_dashboard_service)) -> TableEnvelope:
    frame = service.recent_alert_events(limit=limit)
    return TableEnvelope(rows=frame.to_dict(orient="records"))
