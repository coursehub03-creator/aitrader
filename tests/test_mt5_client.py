from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from core import mt5_client as mt5_module
from core.mt5_client import MT5Client


class FakeMT5:
    TIMEFRAME_M1 = 1
    TIMEFRAME_M5 = 5
    TIMEFRAME_M15 = 15
    TIMEFRAME_H1 = 16385

    def __init__(self) -> None:
        self.initialized = False
        self.selected: dict[str, bool] = {}

    def initialize(self, **_: object) -> bool:
        self.initialized = True
        return True

    def shutdown(self) -> None:
        self.initialized = False

    def last_error(self) -> tuple[int, str]:
        return (0, "OK")

    def symbols_get(self) -> list[SimpleNamespace]:
        return [SimpleNamespace(name="EURUSD"), SimpleNamespace(name="GBPUSD")]

    def symbol_info(self, symbol: str) -> SimpleNamespace | None:
        if symbol == "MISSING":
            return None
        visible = symbol in self.selected
        return SimpleNamespace(visible=visible)

    def symbol_select(self, symbol: str, visible: bool) -> bool:
        if symbol == "LOCKED":
            return False
        self.selected[symbol] = visible
        return True

    def copy_rates_from_pos(
        self,
        symbol: str,
        timeframe: int,
        _start_pos: int,
        count: int,
    ) -> list[dict[str, float | int]] | None:
        if symbol == "EMPTY":
            return None

        return [
            {
                "time": 1_700_000_000 + i * 60,
                "open": 1.1 + i * 0.0001,
                "high": 1.2 + i * 0.0001,
                "low": 1.0 + i * 0.0001,
                "close": 1.15 + i * 0.0001,
                "tick_volume": 100 + i,
                "timeframe": timeframe,
            }
            for i in range(count)
        ]


def test_initialize_symbols_and_fetch(monkeypatch) -> None:
    fake_mt5 = FakeMT5()
    monkeypatch.setattr(mt5_module, "mt5", fake_mt5)

    client = MT5Client()
    assert client.initialize()

    assert client.get_available_symbols() == ["EURUSD", "GBPUSD"]

    candles = client.fetch_rates("EURUSD", "M5", 3)
    assert list(candles.columns) == ["time", "open", "high", "low", "close", "volume"]
    assert len(candles) == 3
    assert pd.api.types.is_datetime64tz_dtype(candles["time"])


def test_symbol_and_timeframe_validation(monkeypatch) -> None:
    fake_mt5 = FakeMT5()
    monkeypatch.setattr(mt5_module, "mt5", fake_mt5)

    client = MT5Client()
    assert client.initialize()

    assert not client.ensure_symbol_selected("MISSING")

    bad_tf = client.fetch_rates("EURUSD", "M2", 5)
    assert bad_tf.empty
    assert "Unsupported timeframe" in client.status_message


def test_fetch_multi_timeframe_rates(monkeypatch) -> None:
    fake_mt5 = FakeMT5()
    monkeypatch.setattr(mt5_module, "mt5", fake_mt5)

    client = MT5Client()
    assert client.initialize()

    results = client.fetch_multi_timeframe_rates("EURUSD", ["M1", "M15", "H1"], 2)
    assert set(results.keys()) == {"M1", "M15", "H1"}
    assert all(len(frame) == 2 for frame in results.values())


def test_timeframe_roundtrip() -> None:
    assert MT5Client.timeframe_to_mt5_constant("M5") == 5
    assert MT5Client.mt5_constant_to_timeframe(16385) == "H1"
