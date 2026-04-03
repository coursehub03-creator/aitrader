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
    side: str
    entry: float
    exit_price: float
    stop_loss: float
    take_profit: float
    open_time: datetime
    close_time: datetime
    outcome: str
    pnl: float
    is_win: bool


@dataclass(slots=True)
class StrategyScore:
    strategy_name: str
    score: float
    net_pnl: float
    trades: int
    max_drawdown: float
    win_rate: float
    loss_rate: float
    average_pnl: float
    profit_factor: float
    expectancy: float = 0.0

    def __post_init__(self) -> None:
        if self.expectancy is None:
            self.expectancy = 0.0


@dataclass(slots=True)
class FinalRecommendation:
    symbol: str
    timeframe: str
    action: str
    market_price: float
    entry: float
    stop_loss: float
    take_profit: float
    risk_reward: float
    confidence: float
    selected_strategy: str
    market_status: str
    news_status: str
    mt5_connection_status: str = "unknown"
    signal_strength: str = "weak"
    rejection_reason: str | None = None
    volatility_state: str = "normal"
    next_news_event: dict[str, Any] | None = None
    reasons: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)

    @property
    def final_action(self) -> str:
        return self.action

    @property
    def risk_reward_ratio(self) -> float:
        return self.risk_reward

    @property
    def selected_strategy_name(self) -> str:
        return self.selected_strategy
