"""MetaTrader 5 integration layer with clean OHLCV data output."""

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

TIMEFRAME_ALIASES = {
    "M1": "TIMEFRAME_M1",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1",
}

FALLBACK_TIMEFRAME_VALUES = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "M30": 30,
    "H1": 16385,
    "H4": 16388,
    "D1": 16408,
}


class MT5Client:
    """Thin MT5 wrapper that never crashes app when MT5 is unavailable."""

    def __init__(self) -> None:
        self.connected = False
        self.status_message = "MT5 client not initialized"

    def initialize(self) -> bool:
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

        try:
            self.connected = bool(mt5.initialize(**kwargs))
        except Exception as exc:  # pragma: no cover - defensive layer
            self.connected = False
            self.status_message = f"MT5 initialize call failed: {exc}"
            LOGGER.exception(self.status_message)
            return False

        if not self.connected:
            err = mt5.last_error()
            self.status_message = f"Failed to initialize MT5 terminal: {err}"
            LOGGER.warning(self.status_message)
            return False

        self.status_message = "Connected to MT5 terminal"
        LOGGER.info(self.status_message)
        return True

    def connect(self) -> bool:
        """Backward-compatible alias for initialize()."""
        return self.initialize()

    def shutdown(self) -> None:
        if mt5 is None:
            self.connected = False
            return

        if self.connected:
            try:
                mt5.shutdown()
            except Exception as exc:  # pragma: no cover - defensive layer
                LOGGER.exception("Failed to shutdown MT5 session cleanly: %s", exc)
            finally:
                self.connected = False
                self.status_message = "MT5 terminal connection closed"

    def get_available_symbols(self) -> list[str]:
        """Return all symbol names available in the connected MT5 terminal."""
        if not self.connected or mt5 is None:
            self.status_message = "MT5 is not connected"
            return []

        try:
            symbols = mt5.symbols_get() or []
        except Exception as exc:
            self.status_message = f"Failed to fetch symbol list: {exc}"
            LOGGER.exception(self.status_message)
            return []

        return [str(item.name) for item in symbols if getattr(item, "name", None)]

    def ensure_symbol_selected(self, symbol: str) -> bool:
        """Ensure a symbol exists and is visible in Market Watch."""
        if not self.connected or mt5 is None:
            self.status_message = "MT5 is not connected"
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

    def ensure_symbol(self, symbol: str) -> bool:
        """Backward-compatible alias for ensure_symbol_selected()."""
        return self.ensure_symbol_selected(symbol)

    def fetch_rates(self, symbol: str, timeframe: str, bars: int) -> pd.DataFrame:
        """Fetch OHLCV rates and return a standardized DataFrame."""
        if bars <= 0:
            self.status_message = "Bars must be a positive integer"
            LOGGER.warning(self.status_message)
            return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])

        if not self.connected or mt5 is None:
            self.status_message = "MT5 is not connected"
            return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])

        if not self.ensure_symbol_selected(symbol):
            return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])

        try:
            mt5_tf = self.timeframe_to_mt5_constant(timeframe)
        except ValueError as exc:
            self.status_message = str(exc)
            LOGGER.warning(self.status_message)
            return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])

        try:
            rates = mt5.copy_rates_from_pos(symbol, mt5_tf, 0, bars)
        except Exception as exc:
            self.status_message = f"Failed to fetch OHLCV data for {symbol}/{timeframe}: {exc}"
            LOGGER.exception(self.status_message)
            return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])

        if rates is None:
            self.status_message = f"No rates returned for {symbol}/{timeframe}"
            LOGGER.warning(self.status_message)
            return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])

        return self._to_ohlcv_dataframe(rates)

    def get_ohlcv(self, symbol: str, timeframe: str, bars: int) -> pd.DataFrame:
        """Backward-compatible alias for fetch_rates()."""
        return self.fetch_rates(symbol, timeframe, bars)

    def fetch_multi_timeframe_rates(
        self,
        symbol: str,
        timeframes: list[str],
        bars: int,
    ) -> dict[str, pd.DataFrame]:
        """Fetch OHLCV data for multiple timeframes."""
        return {tf.upper(): self.fetch_rates(symbol, tf, bars) for tf in timeframes}

    @staticmethod
    def now() -> datetime:
        return datetime.utcnow()

    @staticmethod
    def timeframe_to_mt5_constant(timeframe: str) -> int:
        """Convert string timeframe (M1/M5/M15/H1/...) into MT5 constant."""
        tf = timeframe.upper()
        if tf not in TIMEFRAME_ALIASES:
            raise ValueError(
                f"Unsupported timeframe '{timeframe}'. "
                f"Supported values: {', '.join(TIMEFRAME_ALIASES.keys())}"
            )

        if mt5 is not None:
            attr = TIMEFRAME_ALIASES[tf]
            if hasattr(mt5, attr):
                return int(getattr(mt5, attr))

        return FALLBACK_TIMEFRAME_VALUES[tf]

    @staticmethod
    def mt5_constant_to_timeframe(constant: int) -> str:
        """Convert MT5 timeframe constant back to common string format."""
        for tf, fallback_value in FALLBACK_TIMEFRAME_VALUES.items():
            if fallback_value == int(constant):
                return tf

        if mt5 is not None:
            for tf, attr in TIMEFRAME_ALIASES.items():
                if hasattr(mt5, attr) and int(getattr(mt5, attr)) == int(constant):
                    return tf

        raise ValueError(f"Unknown MT5 timeframe constant: {constant}")

    @staticmethod
    def _to_ohlcv_dataframe(rates: Any) -> pd.DataFrame:
        columns = ["time", "open", "high", "low", "close", "volume"]
        df = pd.DataFrame(rates)
        if df.empty:
            return pd.DataFrame(columns=columns)

        required_input = {"time", "open", "high", "low", "close"}
        if not required_input.issubset(df.columns):
            missing = ", ".join(sorted(required_input - set(df.columns)))
            raise ValueError(f"MT5 rates payload missing required columns: {missing}")

        if "tick_volume" in df.columns:
            df["volume"] = df["tick_volume"]
        elif "real_volume" in df.columns:
            df["volume"] = df["real_volume"]
        elif "volume" not in df.columns:
            df["volume"] = 0

        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        standardized = df[columns].copy()
        return standardized.reset_index(drop=True)
