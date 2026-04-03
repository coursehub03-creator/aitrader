"""MetaTrader 5 integration layer with clean OHLCV data output."""

from __future__ import annotations

import logging
import os
import time
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

    def __init__(
        self,
        terminal_path: str | None = None,
        login: int | None = None,
        password: str | None = None,
        server: str | None = None,
        init_retries: int = 3,
        retry_delay_seconds: float = 0.5,
    ) -> None:
        self.connected = False
        self.status_message = "MT5 client not initialized"
        self.terminal_path = terminal_path
        self.login = login
        self.password = password
        self.server = server
        self.init_retries = max(1, int(init_retries))
        self.retry_delay_seconds = max(0.0, float(retry_delay_seconds))

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
        configured_path = self.terminal_path or os.getenv("MT5_PATH")
        configured_login = self.login if self.login is not None else int(os.getenv("MT5_LOGIN", "0") or 0)
        configured_password = self.password if self.password is not None else os.getenv("MT5_PASSWORD")
        configured_server = self.server if self.server is not None else os.getenv("MT5_SERVER")
        if configured_path:
            kwargs["path"] = configured_path
        if configured_login:
            kwargs["login"] = configured_login
            kwargs["password"] = configured_password
            kwargs["server"] = configured_server

        for attempt in range(1, self.init_retries + 1):
            try:
                self.connected = bool(mt5.initialize(**kwargs))
            except Exception as exc:  # pragma: no cover - defensive layer
                self.connected = False
                self.status_message = f"MT5 initialize call failed: {exc}"
                LOGGER.exception(self.status_message)
            if self.connected:
                break

            err = mt5.last_error()
            self.status_message = (
                f"Failed to initialize MT5 terminal (attempt {attempt}/{self.init_retries}): {err}"
            )
            LOGGER.warning(self.status_message)
            if attempt < self.init_retries:
                time.sleep(self.retry_delay_seconds)

        if not self.connected:
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

    def fetch_rates_range(
        self,
        symbol: str,
        timeframe: str,
        from_time: datetime,
        to_time: datetime,
    ) -> pd.DataFrame:
        """Fetch OHLCV rates for a specific datetime range."""
        if not self.connected or mt5 is None:
            self.status_message = "MT5 is not connected"
            return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
        if to_time <= from_time:
            self.status_message = "Invalid historical range: to_time must be greater than from_time"
            return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
        if not self.ensure_symbol_selected(symbol):
            return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])

        try:
            mt5_tf = self.timeframe_to_mt5_constant(timeframe)
        except ValueError as exc:
            self.status_message = str(exc)
            return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])

        try:
            rates = mt5.copy_rates_range(symbol, mt5_tf, from_time, to_time)
        except Exception as exc:
            self.status_message = f"Failed to fetch historical OHLCV range for {symbol}/{timeframe}: {exc}"
            LOGGER.exception(self.status_message)
            return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])

        if rates is None or len(rates) == 0:
            self.status_message = f"No historical rates returned for {symbol}/{timeframe} in selected range"
            return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])

        return self._to_ohlcv_dataframe(rates)

    def detect_market_status(self, symbol: str, timeframe: str) -> tuple[str, str]:
        """Return market status and reason for a symbol/timeframe pair.

        Status values:
        - open
        - closed
        - unavailable
        - mt5_unavailable
        """
        if mt5 is None or not self.connected:
            self.status_message = "MT5 is not connected"
            return "mt5_unavailable", self.status_message

        if not self.ensure_symbol_selected(symbol):
            return "unavailable", self.status_message

        info = mt5.symbol_info(symbol)
        if info is None:
            self.status_message = f"Symbol '{symbol}' is not available in MT5 terminal"
            return "unavailable", self.status_message

        trade_mode = getattr(info, "trade_mode", None)
        disabled_mode = getattr(mt5, "SYMBOL_TRADE_MODE_DISABLED", None)
        if disabled_mode is not None and trade_mode == disabled_mode:
            self.status_message = f"Symbol '{symbol}' is not tradable in MT5 terminal"
            return "unavailable", self.status_message

        try:
            mt5_tf = self.timeframe_to_mt5_constant(timeframe)
        except ValueError as exc:
            self.status_message = str(exc)
            return "unavailable", self.status_message

        timeframe_seconds = self._timeframe_seconds(timeframe)
        stale_after = max(300, timeframe_seconds * 3)
        now_ts = int(datetime.utcnow().timestamp())

        tick_fetch = getattr(mt5, "symbol_info_tick", None)
        if callable(tick_fetch):
            try:
                tick = tick_fetch(symbol)
            except Exception:
                tick = None
            tick_time = int(getattr(tick, "time", 0) or 0) if tick is not None else 0
            if tick_time and (now_ts - tick_time) <= stale_after:
                return "open", "Recent MT5 tick confirms market is open"

        try:
            rates = mt5.copy_rates_from_pos(symbol, mt5_tf, 0, 2)
        except Exception as exc:
            self.status_message = f"Failed to fetch market status candles for {symbol}/{timeframe}: {exc}"
            LOGGER.exception(self.status_message)
            return "closed", self.status_message

        if rates is None or len(rates) == 0:
            self.status_message = f"No recent rates for {symbol}/{timeframe}; market likely closed"
            return "closed", self.status_message

        try:
            df = pd.DataFrame(rates)
        except Exception as exc:
            self.status_message = (
                f"Invalid rates payload for {symbol}/{timeframe}; "
                f"market status fallback to closed: {exc}"
            )
            LOGGER.warning(self.status_message)
            return "closed", self.status_message

        if df.empty:
            self.status_message = f"No recent rates for {symbol}/{timeframe}; market likely closed"
            return "closed", self.status_message

        if "time" not in df.columns:
            self.status_message = (
                f"MT5 rates missing time column for {symbol}/{timeframe}; "
                "market status fallback to closed"
            )
            LOGGER.warning(self.status_message)
            return "closed", self.status_message

        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True, errors="coerce")
        latest_time_value = df.iloc[-1]["time"]
        if pd.isna(latest_time_value):
            self.status_message = (
                f"MT5 rates contain invalid time values for {symbol}/{timeframe}; "
                "market status fallback to closed"
            )
            LOGGER.warning(self.status_message)
            return "closed", self.status_message

        latest_time = int(latest_time_value.timestamp())
        if (now_ts - latest_time) <= stale_after:
            return "open", "Recent MT5 candles confirm market is open"

        self.status_message = f"Latest rate for {symbol}/{timeframe} is stale; market likely closed"
        return "closed", self.status_message

    def fetch_multi_timeframe_rates(
        self,
        symbol: str,
        timeframes: list[str],
        bars: int,
    ) -> dict[str, pd.DataFrame]:
        """Fetch OHLCV data for multiple timeframes."""
        return {tf.upper(): self.fetch_rates(symbol, tf, bars) for tf in timeframes}

    def get_spread(self, symbol: str) -> float:
        """Return current symbol spread in points when available."""
        if mt5 is None or not self.connected:
            return 0.0
        if not self.ensure_symbol_selected(symbol):
            return 0.0
        try:
            info = mt5.symbol_info(symbol)
            if info is None:
                return 0.0
            spread = float(getattr(info, "spread", 0.0) or 0.0)
            if spread > 0:
                return spread
            tick = mt5.symbol_info_tick(symbol)
            point = float(getattr(info, "point", 0.0) or 0.0)
            bid = float(getattr(tick, "bid", 0.0) or 0.0) if tick is not None else 0.0
            ask = float(getattr(tick, "ask", 0.0) or 0.0) if tick is not None else 0.0
            if point > 0 and bid > 0 and ask > 0:
                return max(0.0, (ask - bid) / point)
        except Exception as exc:  # pragma: no cover
            LOGGER.debug("Could not fetch spread for %s: %s", symbol, exc)
        return 0.0

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
    def _timeframe_seconds(timeframe: str) -> int:
        mapping = {
            "M1": 60,
            "M5": 300,
            "M15": 900,
            "M30": 1800,
            "H1": 3600,
            "H4": 14400,
            "D1": 86400,
        }
        return mapping.get(timeframe.upper(), 300)

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
