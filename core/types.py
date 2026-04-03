"""Domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class SignalAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    NO_TRADE = "NO_TRADE"


@dataclass(slots=True)
class NewsEvent:
    event_id: str
    title: str
    currency: str
    impact: str
    event_time: datetime
    actual: str | None
    forecast: str | None
    previous: str | None
    source: str


@dataclass(slots=True)
class StrategySignal:
    strategy_name: str
    action: str
    entry: float
    stop_loss: float
    take_profit: float
    confidence: float
    reasons: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def no_trade(
        cls,
        strategy_name: str,
        reason: str,
        confidence: float = 0.0,
        entry: float = 0.0,
    ) -> "StrategySignal":
        return cls(strategy_name, SignalAction.NO_TRADE, entry, 0.0, 0.0, confidence, [reason])

    @property
    def reason(self) -> str:
        return "; ".join(self.reasons)


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
