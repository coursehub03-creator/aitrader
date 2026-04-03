"""Paper trade endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.dependencies import get_dashboard_service
from api.schemas import TableEnvelope
from ui.dashboard_service import DashboardService

router = APIRouter(prefix="/paper-trades", tags=["paper-trades"])


@router.get("", response_model=TableEnvelope)
def list_paper_trades(limit: int = 100, service: DashboardService = Depends(get_dashboard_service)) -> TableEnvelope:
    frame = service.load_paper_trades(limit=limit)
    return TableEnvelope(rows=frame.to_dict(orient="records"))
