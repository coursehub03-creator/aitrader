"""Shared strategy calculation helpers."""

from __future__ import annotations

import pandas as pd

from core.indicators import atr as _atr
from core.indicators import ema as _ema
from core.indicators import rsi as _rsi


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential moving average wrapper for strategy layer."""
    return _ema(series, period)


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative strength index wrapper for strategy layer."""
    return _rsi(series, period)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average true range wrapper for strategy layer."""
    return _atr(df, period)


def breakout_levels(df: pd.DataFrame, lookback: int) -> tuple[float, float]:
    """Return high/low breakout levels from prior candles (excluding current)."""
    recent = df.iloc[-lookback - 1 : -1]
    return float(recent["high"].max()), float(recent["low"].min())


def is_breakout_up(price: float, breakout_high: float) -> bool:
    return price > breakout_high


def is_breakout_down(price: float, breakout_low: float) -> bool:
    return price < breakout_low
