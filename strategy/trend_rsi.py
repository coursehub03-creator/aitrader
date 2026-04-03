"""Trend + RSI strategy."""

from __future__ import annotations

from typing import Any

import pandas as pd

from core.indicators import ema, rsi
from core.types import StrategySignal
from strategy.base import TradingStrategy


class TrendRSIStrategy(TradingStrategy):
    name = "trend_rsi"

    def generate_signal(self, df: pd.DataFrame, params: dict[str, Any]) -> StrategySignal | None:
        required = max(params["ema_slow"], params["rsi_period"]) + 2
        if len(df) < required:
            return None

        data = df.copy()
        data["ema_fast"] = ema(data["close"], params["ema_fast"])
        data["ema_slow"] = ema(data["close"], params["ema_slow"])
        data["rsi"] = rsi(data["close"], params["rsi_period"])

        last = data.iloc[-1]
        price = float(last["close"])

        if last["ema_fast"] > last["ema_slow"] and last["rsi"] >= params["rsi_buy_threshold"]:
            return StrategySignal(self.name, "Buy", price, price * 0.997, price * 1.006, 0.62, "Bull trend + RSI")
        if last["ema_fast"] < last["ema_slow"] and last["rsi"] <= params["rsi_sell_threshold"]:
            return StrategySignal(self.name, "Sell", price, price * 1.003, price * 0.994, 0.62, "Bear trend + RSI")
        return None
