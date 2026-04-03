"""Breakout + ATR strategy."""

from __future__ import annotations

from typing import Any

import pandas as pd

from core.types import SignalAction, StrategySignal
from strategy.base import BaseStrategy
from strategy.helpers import atr, breakout_levels, is_breakout_down, is_breakout_up


class BreakoutATRStrategy(BaseStrategy):
    name = "breakout_atr"

    @property
    def parameter_schema(self) -> dict[str, dict[str, Any]]:
        return {
            "breakout_lookback": {"type": "int", "min": 5, "max": 120, "default": 20},
            "atr_period": {"type": "int", "min": 5, "max": 50, "default": 14},
            "atr_sl_multiplier": {"type": "float", "min": 0.5, "max": 5.0, "default": 1.5},
            "atr_tp_multiplier": {"type": "float", "min": 1.0, "max": 8.0, "default": 2.5},
            "base_confidence": {"type": "float", "min": 0.1, "max": 1.0, "default": 0.59},
        }

    def generate_signal(self, df: pd.DataFrame, params: dict[str, Any]) -> StrategySignal:
        lookback = params["breakout_lookback"]
        period = params["atr_period"]
        if len(df) < max(lookback, period) + 2:
            return StrategySignal.no_trade(self.name, "Insufficient data")

        data = df.copy()
        data["atr"] = atr(data, period)
        last = data.iloc[-1]
        price = float(last["close"])
        atr_value = float(last["atr"])
        if atr_value <= 0:
            return StrategySignal.no_trade(self.name, "ATR is not available", entry=price)

        high_break, low_break = breakout_levels(data, lookback)
        confidence = float(params["base_confidence"])

        if is_breakout_up(price, high_break):
            sl = price - atr_value * params["atr_sl_multiplier"]
            tp = price + atr_value * params["atr_tp_multiplier"]
            return StrategySignal(
                self.name,
                SignalAction.BUY,
                price,
                sl,
                tp,
                confidence,
                ["Price closed above breakout high", "ATR-based risk controls applied"],
            )
        if is_breakout_down(price, low_break):
            sl = price + atr_value * params["atr_sl_multiplier"]
            tp = price - atr_value * params["atr_tp_multiplier"]
            return StrategySignal(
                self.name,
                SignalAction.SELL,
                price,
                sl,
                tp,
                confidence,
                ["Price closed below breakout low", "ATR-based risk controls applied"],
            )

        return StrategySignal.no_trade(
            self.name,
            "No breakout beyond configured lookback",
            confidence=0.4,
            entry=price,
        )
