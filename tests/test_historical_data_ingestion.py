from __future__ import annotations

from pathlib import Path

import pandas as pd

from learning.historical_data import HistoricalDataPipeline
from learning.persistence import LearningPersistence, StorageLayout


class FakeMT5Client:
    def __init__(self, frame: pd.DataFrame | None = None, connected: bool = True, status_message: str = "ok") -> None:
        self.connected = connected
        self.status_message = status_message
        self._frame = frame if frame is not None else pd.DataFrame()

    def connect(self) -> bool:
        return self.connected

    def fetch_rates_range(self, *_args, **_kwargs) -> pd.DataFrame:
        return self._frame.copy()

    def ensure_symbol_selected(self, *_args, **_kwargs) -> bool:
        return True


def test_historical_fetch_updates_inventory(tmp_path: Path) -> None:
    frame = pd.DataFrame(
        [
            {"time": "2026-01-01T00:00:00+00:00", "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05, "volume": 100},
            {"time": "2026-01-02T00:00:00+00:00", "open": 1.05, "high": 1.2, "low": 1.0, "close": 1.15, "volume": 120},
        ]
    )
    persistence = LearningPersistence(StorageLayout(root=tmp_path))
    pipeline = HistoricalDataPipeline(FakeMT5Client(frame=frame), persistence=persistence)

    result = pipeline.fetch_and_store_with_result("EURUSD", "M5", 30)
    assert result.success is True
    assert result.status == "ok"

    inventory = persistence.load_market_history_inventory()
    assert len(inventory) == 1
    assert inventory.loc[0, "symbol"] == "EURUSD"
    assert inventory.loc[0, "timeframe"] == "M5"
    assert int(inventory.loc[0, "candles"]) == 2


def test_historical_fetch_handles_mt5_unavailable(tmp_path: Path) -> None:
    persistence = LearningPersistence(StorageLayout(root=tmp_path))
    mt5 = FakeMT5Client(frame=pd.DataFrame(), connected=False, status_message="MT5 is not connected")
    pipeline = HistoricalDataPipeline(mt5, persistence=persistence)

    result = pipeline.fetch_and_store_with_result("EURUSD", "M5", 30)
    assert result.success is False
    assert result.status == "mt5_unavailable"
    assert result.candles_fetched == 0


def test_historical_summary_reads_inventory(tmp_path: Path) -> None:
    persistence = LearningPersistence(StorageLayout(root=tmp_path))
    persistence.upsert_market_history_inventory(
        {
            "symbol": "XAUUSD",
            "timeframe": "H1",
            "candles": 250,
            "data_start": "2025-01-01T00:00:00+00:00",
            "data_end": "2025-03-01T00:00:00+00:00",
            "last_fetch_time": "2026-01-01T00:00:00+00:00",
            "storage_path": "data/market_history/XAUUSD_H1.csv",
            "fetch_status": "ok",
        }
    )

    pipeline = HistoricalDataPipeline(FakeMT5Client(), persistence=persistence)
    summary = pipeline.summary()
    assert len(summary) == 1
    assert summary.loc[0, "symbol"] == "XAUUSD"
    assert summary.loc[0, "fetch_status"] == "ok"
