"""Market data endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.dependencies import get_dashboard_service
from api.schemas import MarketDataEnvelope
from ui.dashboard_service import DashboardService

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/candles", response_model=MarketDataEnvelope)
def candles(
    symbol: str = "EURUSD",
    timeframe: str = "M5",
    bars: int = 300,
    service: DashboardService = Depends(get_dashboard_service),
) -> MarketDataEnvelope:
    frame, status_message = service.refresh_market_data(symbol=symbol, timeframe=timeframe, bars=bars)
    return MarketDataEnvelope(
        symbol=symbol.upper(),
        timeframe=timeframe.upper(),
        bars=bars,
        status_message=status_message,
        candles=frame.to_dict(orient="records"),
    )
