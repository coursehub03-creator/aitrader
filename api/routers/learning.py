"""Learning center endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.dependencies import get_dashboard_service
from ui.dashboard_service import DashboardService

router = APIRouter(prefix="/learning", tags=["learning"])


@router.get("/center")
def learning_center(service: DashboardService = Depends(get_dashboard_service)) -> dict:
    payload = service.learning_center_payload()
    payload["events"] = payload.get("events", []).to_dict(orient="records")
    payload["health"] = dict(payload.get("health", {}))
    return payload
