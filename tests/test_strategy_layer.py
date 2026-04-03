import pandas as pd

from core.types import SignalAction
from strategy.breakout_atr import BreakoutATRStrategy
from strategy.registry import STRATEGY_REGISTRY, create_default_strategies, get_parameter_schemas
from strategy.trend_rsi import TrendRSIStrategy


def _candles(rows: int = 120) -> pd.DataFrame:
    prices = [1.0 + i * 0.001 for i in range(rows)]
    return pd.DataFrame(
        {
            "open": prices,
            "high": [p + 0.0008 for p in prices],
            "low": [p - 0.0008 for p in prices],
            "close": prices,
            "volume": [100] * rows,
        }
    )


def test_trend_rsi_returns_normalized_signal_shape() -> None:
    signal = TrendRSIStrategy().generate_signal(
        _candles(),
        {
            "ema_fast": 5,
            "ema_slow": 20,
            "rsi_period": 14,
            "rsi_buy_threshold": 50,
            "rsi_sell_threshold": 45,
            "sl_pct": 0.003,
            "tp_pct": 0.006,
            "base_confidence": 0.62,
        },
    )

    assert signal.action in {SignalAction.BUY, SignalAction.SELL, SignalAction.NO_TRADE}
    assert isinstance(signal.reasons, list)
    assert 0.0 <= signal.confidence <= 1.0


def test_breakout_atr_returns_normalized_signal_shape() -> None:
    signal = BreakoutATRStrategy().generate_signal(
        _candles(),
        {
            "breakout_lookback": 20,
            "atr_period": 14,
            "atr_sl_multiplier": 1.5,
            "atr_tp_multiplier": 2.5,
            "base_confidence": 0.59,
        },
    )

    assert signal.action in {SignalAction.BUY, SignalAction.SELL, SignalAction.NO_TRADE}
    assert isinstance(signal.reasons, list)


def test_strategy_registry_and_schemas() -> None:
    assert "trend_rsi" in STRATEGY_REGISTRY
    assert "breakout_atr" in STRATEGY_REGISTRY
    assert len(create_default_strategies()) == 2

    schemas = get_parameter_schemas()
    assert "ema_fast" in schemas["trend_rsi"]
    assert "atr_period" in schemas["breakout_atr"]
