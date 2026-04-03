"""Breakout + ATR strategy."""

from __future__ import annotations

from typing import Any

import pandas as pd

from core.indicators import atr
from core.types import StrategySignal
from strategy.base import TradingStrategy


class BreakoutATRStrategy(TradingStrategy):
    name = "breakout_atr"

    def generate_signal(self, df: pd.DataFrame, params: dict[str, Any]) -> StrategySignal | None:
        lookback = params["breakout_lookback"]
        period = params["atr_period"]
        if len(df) < max(lookback, period) + 2:
            return None

        data = df.copy()
        data["atr"] = atr(data, period)
        last = data.iloc[-1]
        recent = data.iloc[-lookback - 1 : -1]
        price = float(last["close"])
        atr_value = float(last["atr"])
        if atr_value <= 0:
            return None

        high_break = float(recent["high"].max())
        low_break = float(recent["low"].min())

        if price > high_break:
            sl = price - atr_value * params["atr_sl_multiplier"]
            tp = price + atr_value * params["atr_tp_multiplier"]
            return StrategySignal(self.name, "Buy", price, sl, tp, 0.59, "Bull breakout + ATR")
        if price < low_break:
            sl = price + atr_value * params["atr_sl_multiplier"]
            tp = price - atr_value * params["atr_tp_multiplier"]
            return StrategySignal(self.name, "Sell", price, sl, tp, 0.59, "Bear breakout + ATR")
        return None
