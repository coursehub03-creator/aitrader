"""MetaTrader5 connector with safe import and clear status reporting."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

import pandas as pd

try:
    import MetaTrader5 as mt5
except Exception:  # pragma: no cover - environment dependent
    mt5 = None

LOGGER = logging.getLogger(__name__)


class MT5Client:
    """Thin MT5 wrapper that never crashes app when MT5 is unavailable."""

    def __init__(self) -> None:
        self.connected = False
        self.status_message = "MT5 client not initialized"

    def connect(self) -> bool:
        """Initialize MT5 terminal connection and keep a human-readable status."""
        if mt5 is None:
            self.connected = False
            self.status_message = (
                "MetaTrader5 Python package is not installed. "
                "Install dependencies and ensure MT5 terminal is available."
            )
            LOGGER.warning(self.status_message)
            return False

        kwargs: dict[str, Any] = {}
        if os.getenv("MT5_PATH"):
            kwargs["path"] = os.getenv("MT5_PATH")
        if os.getenv("MT5_LOGIN"):
            kwargs["login"] = int(os.getenv("MT5_LOGIN", "0"))
            kwargs["password"] = os.getenv("MT5_PASSWORD")
            kwargs["server"] = os.getenv("MT5_SERVER")

        self.connected = bool(mt5.initialize(**kwargs))
        if not self.connected:
            err = mt5.last_error()
            self.status_message = f"Failed to initialize MT5 terminal: {err}"
            LOGGER.warning(self.status_message)
            return False

        self.status_message = "Connected to MT5 terminal"
        LOGGER.info(self.status_message)
        return True

    def shutdown(self) -> None:
        if mt5 is not None and self.connected:
            mt5.shutdown()
            self.connected = False
            self.status_message = "MT5 terminal connection closed"

    def ensure_symbol(self, symbol: str) -> bool:
        if not self.connected or mt5 is None:
            return False

        info = mt5.symbol_info(symbol)
        if info is None:
            self.status_message = f"Symbol '{symbol}' is not available in MT5 terminal"
            LOGGER.warning(self.status_message)
            return False

        if not info.visible and not mt5.symbol_select(symbol, True):
            self.status_message = f"Could not enable symbol '{symbol}' in Market Watch"
            LOGGER.warning(self.status_message)
            return False

        return True

    def get_ohlcv(self, symbol: str, timeframe: str, bars: int) -> pd.DataFrame:
        if not self.connected or mt5 is None:
            return pd.DataFrame()

        mt5_tf = self._resolve_timeframe(timeframe)
        rates = mt5.copy_rates_from_pos(symbol, mt5_tf, 0, bars)

        if rates is None:
            self.status_message = f"Failed to fetch OHLCV data for {symbol}/{timeframe}"
            LOGGER.warning(self.status_message)
            return pd.DataFrame()

        df = pd.DataFrame(rates)
        if df.empty:
            self.status_message = f"No OHLCV data returned for {symbol}/{timeframe}"
            LOGGER.warning(self.status_message)
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