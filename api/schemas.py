"""Pydantic schemas for API payloads."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class APIStatus(BaseModel):
    """Standard status envelope."""

    status: str = "ok"


class RecommendationEnvelope(BaseModel):
    """Recommendation response payload."""

    recommendation: dict[str, Any]


class MarketDataEnvelope(BaseModel):
    """Market data response payload."""

    symbol: str
    timeframe: str
    bars: int
    status_message: str
    candles: list[dict[str, Any]] = Field(default_factory=list)


class WatchlistItem(BaseModel):
    """Watchlist entry."""

    symbol: str


class WatchlistEnvelope(BaseModel):
    """Watchlist payload."""

    symbols: list[str] = Field(default_factory=list)


class TableEnvelope(BaseModel):
    """Tabular payload for paper trades, alerts, and learning data."""

    rows: list[dict[str, Any]] = Field(default_factory=list)


class HistoricalFetchRequest(BaseModel):
    symbol: str = "EURUSD"
    timeframe: str = "M5"
    lookback_days: int = Field(default=90, description="Supported: 30, 90, 180, 365")


class HistoricalFetchResponse(BaseModel):
    success: bool
    symbol: str
    timeframe: str
    lookback_days: int
    candles_fetched: int
    date_start: str = ""
    date_end: str = ""
    storage_path: str = ""
    status_message: str


class HistoryInventoryEnvelope(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list)
