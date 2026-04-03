"""MetaTrader5 connector with safe import handling."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

import pandas as pd

try:
    import MetaTrader5 as mt5
except Exception:  # safe import handling per requirement
    mt5 = None

LOGGER = logging.getLogger(__name__)


class MT5Client:
    """Thin MT5 wrapper that never crashes app when MT5 isn't installed."""

    def __init__(self) -> None:
        self.connected = False

    def connect(self) -> None:
        if mt5 is None:
            LOGGER.warning("MetaTrader5 not installed; engine will return No Trade recommendation")
            return

        kwargs: dict[str, Any] = {}
        if os.getenv("MT5_PATH"):
            kwargs["path"] = os.getenv("MT5_PATH")
        if os.getenv("MT5_LOGIN"):
            kwargs["login"] = int(os.getenv("MT5_LOGIN", "0"))
            kwargs["password"] = os.getenv("MT5_PASSWORD")
            kwargs["server"] = os.getenv("MT5_SERVER")

        self.connected = bool(mt5.initialize(**kwargs))
        if not self.connected:
            LOGGER.warning("Failed to initialize MT5: %s", mt5.last_error())

    def shutdown(self) -> None:
        if mt5 is not None and self.connected:
            mt5.shutdown()
            self.connected = False

    def ensure_symbol(self, symbol: str) -> bool:
        if not self.connected or mt5 is None:
            return False
        info = mt5.symbol_info(symbol)
        if info is None:
            return False
        if not info.visible:
            return bool(mt5.symbol_select(symbol, True))
        return True

    def get_ohlcv(self, symbol: str, timeframe: str, bars: int) -> pd.DataFrame:
        if not self.connected or mt5 is None:
            return pd.DataFrame()
        mt5_tf = self._resolve_timeframe(timeframe)
        rates = mt5.copy_rates_from_pos(symbol, mt5_tf, 0, bars)
        if rates is None:
            return pd.DataFrame()

        df = pd.DataFrame(rates)
        if df.empty:
            return df
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df.rename(columns={"tick_volume": "volume"}, inplace=True)
        return df

    @staticmethod
    def now() -> datetime:
        return datetime.utcnow()

    @staticmethod
    def _resolve_timeframe(timeframe: str) -> int:
        fallback_map = {
            "M1": 1,
            "M5": 5,
            "M15": 15,
            "M30": 30,
            "H1": 16385,
            "H4": 16388,
            "D1": 16408,
        }
        if mt5 is not None:
            attr = f"TIMEFRAME_{timeframe.upper()}"
            if hasattr(mt5, attr):
                return int(getattr(mt5, attr))
        return fallback_map.get(timeframe.upper(), 5)
