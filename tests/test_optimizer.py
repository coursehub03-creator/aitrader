import pandas as pd

from learning.optimizer import ParameterOptimizer
from strategy.trend_rsi import TrendRSIStrategy


def test_optimizer_finds_params() -> None:
    rows = 220
    prices = [1.0 + i * 0.0003 for i in range(rows)]
    candles = pd.DataFrame(
        {
            "open": prices,
            "high": [p + 0.0004 for p in prices],
            "low": [p - 0.0004 for p in prices],
            "close": prices,
            "volume": [100] * rows,
        }
    )

    result = ParameterOptimizer(5, 100, 20).optimize(
        strategy=TrendRSIStrategy(),
        candles=candles,
        parameter_grid={
            "ema_fast": [8, 20],
            "ema_slow": [30, 50],
            "rsi_buy_threshold": [50, 55],
            "rsi_sell_threshold": [45],
        },
        symbol="EURUSD",
        fixed_params={"rsi_period": 14},
    )

    assert result is not None
    assert result.strategy_name == "trend_rsi"
    assert result.best_params["rsi_period"] == 14
