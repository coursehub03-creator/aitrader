"""Historical market data ingestion and summary helpers."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

import pandas as pd

from core.mt5_client import MT5Client
from learning.persistence import LearningPersistence


RangeUnit = Literal["days", "weeks", "months"]


class HistoricalDataPipeline:
    def __init__(self, mt5_client: MT5Client, persistence: LearningPersistence | None = None) -> None:
        self.mt5 = mt5_client
        self.persistence = persistence or LearningPersistence()

    @staticmethod
    def _resolve_range(value: int, unit: RangeUnit) -> timedelta:
        if unit == "days":
            return timedelta(days=value)
        if unit == "weeks":
            return timedelta(weeks=value)
        if unit == "months":
            return timedelta(days=value * 30)
        raise ValueError(f"Unsupported range unit: {unit}")

    def fetch_and_store(self, symbol: str, timeframe: str, lookback_value: int, lookback_unit: RangeUnit) -> tuple[pd.DataFrame, Path]:
        if not self.mt5.connected:
            self.mt5.connect()
        if not self.mt5.connected:
            return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"]), Path()

        end_time = datetime.utcnow()
        start_time = end_time - self._resolve_range(lookback_value, lookback_unit)
        candles = self.mt5.fetch_rates_range(symbol.upper(), timeframe.upper(), start_time, end_time)
        if candles.empty:
            return candles, Path()

        path = self.persistence.layout.market_history_dir / f"{symbol.upper()}_{timeframe.upper()}.csv"
        if path.exists():
            existing = pd.read_csv(path)
            combined = pd.concat([existing, candles], ignore_index=True)
            combined["time"] = pd.to_datetime(combined["time"], errors="coerce")
            combined = combined.dropna(subset=["time"]).drop_duplicates(subset=["time"]).sort_values("time")
        else:
            combined = candles.copy()
        combined.to_csv(path, index=False)
        return combined, path

    def load_history(self, symbol: str, timeframe: str) -> pd.DataFrame:
        path = self.persistence.layout.market_history_dir / f"{symbol.upper()}_{timeframe.upper()}.csv"
        return self.persistence.safe_read_csv(path, ["time", "open", "high", "low", "close", "volume"])

    def summary(self) -> pd.DataFrame:
        rows = []
        for path in sorted(self.persistence.layout.market_history_dir.glob("*_*.csv")):
            frame = self.persistence.safe_read_csv(path, ["time", "open", "high", "low", "close", "volume"])
            if frame.empty:
                continue
            symbol, timeframe = path.stem.split("_", 1)
            ts = pd.to_datetime(frame["time"], errors="coerce").dropna()
            if ts.empty:
                continue
            rows.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "data_start": ts.min().isoformat(),
                    "data_end": ts.max().isoformat(),
                    "candles": int(len(frame)),
                }
            )
        return pd.DataFrame(rows)
