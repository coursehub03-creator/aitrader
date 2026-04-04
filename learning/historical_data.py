"""Historical market data ingestion and summary helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import pandas as pd

from core.mt5_client import MT5Client
from learning.persistence import LearningPersistence


RangeUnit = Literal["days", "weeks", "months"]
SUPPORTED_LOOKBACK_DAYS = (30, 90, 180, 365)
OHLCV_COLUMNS = ["time", "open", "high", "low", "close", "volume"]


@dataclass(slots=True)
class HistoricalFetchResult:
    success: bool
    status: str
    symbol: str
    timeframe: str
    lookback_days: int
    candles_fetched: int
    date_start: str
    date_end: str
    storage_path: str
    last_fetch_time: str
    status_message: str


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

    @staticmethod
    def _timeframe_minutes(timeframe: str) -> int:
        mapping = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}
        return mapping.get(str(timeframe).upper(), 0)

    def _empty(self) -> pd.DataFrame:
        return pd.DataFrame(columns=OHLCV_COLUMNS)

    def fetch_and_store(self, symbol: str, timeframe: str, lookback_value: int, lookback_unit: RangeUnit) -> tuple[pd.DataFrame, Path]:
        if not self.mt5.connected:
            self.mt5.connect()
        if not self.mt5.connected:
            return self._empty(), Path()

        end_time = datetime.utcnow()
        start_time = end_time - self._resolve_range(lookback_value, lookback_unit)
        candles = self.mt5.fetch_rates_range(symbol.upper(), timeframe.upper(), start_time, end_time)
        if candles.empty:
            return candles, Path()

        base_path = self.persistence.layout.market_history_dir / f"{symbol.upper()}_{timeframe.upper()}"
        csv_path = base_path.with_suffix(".csv")
        if csv_path.exists():
            existing = self.persistence.safe_read_csv(csv_path, OHLCV_COLUMNS)
            combined = pd.concat([existing, candles], ignore_index=True)
            combined["time"] = pd.to_datetime(combined["time"], errors="coerce")
            combined = combined.dropna(subset=["time"]).drop_duplicates(subset=["time"]).sort_values("time")
        else:
            combined = candles.copy()
        output_path = self.persistence.safe_write_market_history(base_path, combined, prefer_parquet=False)
        return combined, output_path

    def fetch_and_store_days(self, symbol: str, timeframe: str, lookback_days: int) -> tuple[pd.DataFrame, Path]:
        if int(lookback_days) not in SUPPORTED_LOOKBACK_DAYS:
            raise ValueError(
                f"Unsupported lookback window '{lookback_days}'. "
                f"Supported windows: {', '.join(str(item) for item in SUPPORTED_LOOKBACK_DAYS)} days."
            )
        return self.fetch_and_store(symbol=symbol, timeframe=timeframe, lookback_value=int(lookback_days), lookback_unit="days")

    def fetch_and_store_with_result(self, symbol: str, timeframe: str, lookback_days: int) -> HistoricalFetchResult:
        symbol_upper = symbol.upper()
        timeframe_upper = timeframe.upper()
        lookback_days = int(lookback_days)
        last_fetch_time = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
        if lookback_days not in SUPPORTED_LOOKBACK_DAYS:
            raise ValueError(
                f"Unsupported lookback window '{lookback_days}'. "
                f"Supported windows: {', '.join(str(item) for item in SUPPORTED_LOOKBACK_DAYS)} days."
            )

        frame, path = self.fetch_and_store_days(symbol=symbol_upper, timeframe=timeframe_upper, lookback_days=lookback_days)
        if frame.empty:
            status = "mt5_unavailable" if "not connected" in str(self.mt5.status_message).lower() else "empty"
            return HistoricalFetchResult(
                success=False,
                status=status,
                symbol=symbol_upper,
                timeframe=timeframe_upper,
                lookback_days=lookback_days,
                candles_fetched=0,
                date_start="",
                date_end="",
                storage_path="",
                last_fetch_time=last_fetch_time,
                status_message=self.mt5.status_message or "No historical data available.",
            )

        ts = pd.to_datetime(frame["time"], errors="coerce").dropna()
        start = ts.min()
        end = ts.max()
        requested_start = datetime.utcnow() - timedelta(days=lookback_days)
        tf_minutes = self._timeframe_minutes(timeframe_upper)
        partial = bool(tf_minutes and pd.notna(start) and start.to_pydatetime().replace(tzinfo=None) > (requested_start + timedelta(minutes=tf_minutes * 3)))
        status = "partial" if partial else "ok"

        row = {
            "symbol": symbol_upper,
            "timeframe": timeframe_upper,
            "candles": int(len(frame)),
            "data_start": start.isoformat() if pd.notna(start) else "",
            "data_end": end.isoformat() if pd.notna(end) else "",
            "last_fetch_time": last_fetch_time,
            "storage_path": str(path),
            "fetch_status": status,
        }
        self.persistence.upsert_market_history_inventory(row)

        return HistoricalFetchResult(
            success=True,
            status=status,
            symbol=symbol_upper,
            timeframe=timeframe_upper,
            lookback_days=lookback_days,
            candles_fetched=int(len(frame)),
            date_start=row["data_start"],
            date_end=row["data_end"],
            storage_path=str(path),
            last_fetch_time=last_fetch_time,
            status_message="Partial historical coverage fetched." if partial else f"Fetched {len(frame)} candles successfully.",
        )

    def load_history(self, symbol: str, timeframe: str) -> pd.DataFrame:
        base_path = self.persistence.layout.market_history_dir / f"{symbol.upper()}_{timeframe.upper()}"
        csv_path = base_path.with_suffix(".csv")
        parquet_path = base_path.with_suffix(".parquet")
        if parquet_path.exists():
            return self.persistence.safe_read_parquet(parquet_path, OHLCV_COLUMNS)
        return self.persistence.safe_read_csv(csv_path, OHLCV_COLUMNS)

    def summary(self) -> pd.DataFrame:
        inventory = self.persistence.load_market_history_inventory()
        if not inventory.empty:
            return inventory.sort_values(["symbol", "timeframe"]).reset_index(drop=True)
        rows = []
        files = sorted(self.persistence.layout.market_history_dir.glob("*_*.csv")) + sorted(self.persistence.layout.market_history_dir.glob("*_*.parquet"))
        for path in files:
            frame = self.persistence.safe_read_parquet(path, OHLCV_COLUMNS) if path.suffix == ".parquet" else self.persistence.safe_read_csv(path, OHLCV_COLUMNS)
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
                    "last_fetch_time": "",
                    "storage_path": str(path),
                    "fetch_status": "unknown",
                }
            )
        return pd.DataFrame(rows)
