"""Trend + RSI strategy."""

from __future__ import annotations

from typing import Any

import pandas as pd

from core.types import SignalAction, StrategySignal
from strategy.base import BaseStrategy
from strategy.helpers import ema, rsi


class TrendRSIStrategy(BaseStrategy):
    name = "trend_rsi"

    @property
    def parameter_schema(self) -> dict[str, dict[str, Any]]:
        return {
            "ema_fast": {"type": "int", "min": 5, "max": 50, "default": 20},
            "ema_slow": {"type": "int", "min": 10, "max": 200, "default": 50},
            "rsi_period": {"type": "int", "min": 5, "max": 50, "default": 14},
            "rsi_buy_threshold": {"type": "int", "min": 50, "max": 80, "default": 55},
            "rsi_sell_threshold": {"type": "int", "min": 20, "max": 50, "default": 45},
            "sl_pct": {"type": "float", "min": 0.001, "max": 0.02, "default": 0.003},
            "tp_pct": {"type": "float", "min": 0.002, "max": 0.05, "default": 0.006},
            "base_confidence": {"type": "float", "min": 0.1, "max": 1.0, "default": 0.62},
        }

    def generate_signal(self, df: pd.DataFrame, params: dict[str, Any]) -> StrategySignal:
        required = max(params["ema_slow"], params["rsi_period"]) + 2
        if len(df) < required:
            return StrategySignal.no_trade(self.name, "Insufficient data")

        data = df.copy()
        data["ema_fast"] = ema(data["close"], params["ema_fast"])
        data["ema_slow"] = ema(data["close"], params["ema_slow"])
        data["rsi"] = rsi(data["close"], params["rsi_period"])

        last = data.iloc[-1]
        price = float(last["close"])
        confidence = float(params.get("base_confidence", 0.62))
        sl_pct = float(params.get("sl_pct", 0.003))
        tp_pct = float(params.get("tp_pct", 0.006))

        if last["ema_fast"] > last["ema_slow"] and last["rsi"] >= params["rsi_buy_threshold"]:
            return StrategySignal(
                self.name,
                SignalAction.BUY,
                price,
                price * (1 - sl_pct),
                price * (1 + tp_pct),
                confidence,
                ["EMA fast above EMA slow", "RSI confirms bullish momentum"],
            )
        if last["ema_fast"] < last["ema_slow"] and last["rsi"] <= params["rsi_sell_threshold"]:
            return StrategySignal(
                self.name,
                SignalAction.SELL,
                price,
                price * (1 + sl_pct),
                price * (1 - tp_pct),
                confidence,
                ["EMA fast below EMA slow", "RSI confirms bearish momentum"],
            )

        return StrategySignal.no_trade(
            self.name,
            "Trend and RSI conditions not aligned",
            confidence=0.4,
            entry=price,
        )
