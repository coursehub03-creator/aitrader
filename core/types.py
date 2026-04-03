"""Domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class NewsEvent:
    title: str
    currency: str
    impact: str
    event_time: datetime
    source: str


@dataclass(slots=True)
class StrategySignal:
    strategy_name: str
    action: str
    entry: float
    stop_loss: float
    take_profit: float
    confidence: float
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PaperTradeResult:
    strategy_name: str
    symbol: str
    action: str
    entry: float
    exit_price: float
    pnl: float
    is_win: bool
    timestamp: datetime


@dataclass(slots=True)
class StrategyScore:
    strategy_name: str
    score: float
    profit: float
    trades: int
    max_drawdown: float
    win_rate: float
    profit_factor: float


@dataclass(slots=True)
class FinalRecommendation:
    symbol: str
    timeframe: str
    action: str
    entry: float
    stop_loss: float
    take_profit: float
    confidence: float
    reason: str
    contributing_strategies: list[str] = field(default_factory=list)
