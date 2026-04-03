from __future__ import annotations

import time
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
        trade_mode = 1 if symbol != "NOT_TRADABLE" else 0
        return SimpleNamespace(visible=visible, trade_mode=trade_mode)

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
        if symbol == "MALFORMED":
            return [{"open": 1.1, "close": 1.2}]
        if symbol == "STALE_EMPTY":
            return []
        if symbol == "STALE_BAD_STRUCT":
            return [{"open": 1.1}]
        if symbol == "STALE_BAD_TIME":
            return [{"time": "bad"}]

        base_time = int(time.time()) if symbol not in {"STALE", "STALE_EMPTY", "STALE_BAD_STRUCT", "STALE_BAD_TIME"} else 1_700_000_000
        return [
            {
                "time": base_time + i * 60,
                "open": 1.1 + i * 0.0001,
                "high": 1.2 + i * 0.0001,
                "low": 1.0 + i * 0.0001,
                "close": 1.15 + i * 0.0001,
                "tick_volume": 100 + i,
                "timeframe": timeframe,
            }
            for i in range(count)
        ]

    def symbol_info_tick(self, symbol: str) -> SimpleNamespace | None:
        if symbol in {"STALE", "STALE_EMPTY", "STALE_BAD_STRUCT", "STALE_BAD_TIME"}:
            return SimpleNamespace(time=1_700_000_000)
        return SimpleNamespace(time=int(time.time()))


class _RetryMT5(FakeMT5):
    def __init__(self, fail_attempts: int) -> None:
        super().__init__()
        self.fail_attempts = fail_attempts
        self.calls = 0

    def initialize(self, **_: object) -> bool:
        self.calls += 1
        if self.calls <= self.fail_attempts:
            return False
        self.initialized = True
        return True


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


def test_fetch_rates_empty_and_malformed_payloads(monkeypatch) -> None:
    fake_mt5 = FakeMT5()
    monkeypatch.setattr(mt5_module, "mt5", fake_mt5)

    client = MT5Client()
    assert client.initialize()

    empty = client.fetch_rates("EMPTY", "M5", 5)
    assert empty.empty

    malformed = client.fetch_rates("MALFORMED", "M5", 5)
    assert malformed.empty
    assert "Malformed rates returned" in client.status_message


def test_timeframe_roundtrip() -> None:
    assert MT5Client.timeframe_to_mt5_constant("M5") == 5
    assert MT5Client.mt5_constant_to_timeframe(16385) == "H1"


def test_detect_market_status_variants(monkeypatch) -> None:
    fake_mt5 = FakeMT5()
    fake_mt5.SYMBOL_TRADE_MODE_DISABLED = 0
    monkeypatch.setattr(mt5_module, "mt5", fake_mt5)

    client = MT5Client()
    assert client.initialize()

    assert client.detect_market_status("EURUSD", "M5")[0] == "open"
    assert client.detect_market_status("STALE", "M5")[0] == "closed"
    assert client.detect_market_status("STALE_EMPTY", "M5")[0] == "unknown"
    assert client.detect_market_status("STALE_BAD_STRUCT", "M5")[0] == "unknown"
    assert client.detect_market_status("STALE_BAD_TIME", "M5")[0] == "unknown"
    assert client.detect_market_status("MISSING", "M5")[0] == "unavailable"
    assert client.detect_market_status("NOT_TRADABLE", "M5")[0] == "unavailable"


def test_detect_market_status_mt5_unavailable(monkeypatch) -> None:
    fake_mt5 = FakeMT5()
    monkeypatch.setattr(mt5_module, "mt5", fake_mt5)

    client = MT5Client()
    status, _reason = client.detect_market_status("EURUSD", "M5")
    assert status == "mt5_unavailable"


def test_initialize_retries(monkeypatch) -> None:
    fake_mt5 = _RetryMT5(fail_attempts=2)
    monkeypatch.setattr(mt5_module, "mt5", fake_mt5)

    client = MT5Client(init_retries=3, retry_delay_seconds=0.0)
    assert client.initialize()
    assert fake_mt5.calls == 3
