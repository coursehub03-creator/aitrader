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
