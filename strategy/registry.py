"""Strategy registry and factory."""

from __future__ import annotations

from strategy.base import BaseStrategy
from strategy.breakout_atr import BreakoutATRStrategy
from strategy.trend_rsi import TrendRSIStrategy

STRATEGY_REGISTRY: dict[str, type[BaseStrategy]] = {
    TrendRSIStrategy.name: TrendRSIStrategy,
    BreakoutATRStrategy.name: BreakoutATRStrategy,
}


def create_default_strategies() -> list[BaseStrategy]:
    return [cls() for cls in STRATEGY_REGISTRY.values()]


def get_parameter_schemas() -> dict[str, dict[str, dict[str, object]]]:
    return {name: cls().parameter_schema for name, cls in STRATEGY_REGISTRY.items()}
