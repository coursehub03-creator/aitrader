import json

import pandas as pd

from learning.optimizer import ParameterOptimizer
from strategy.trend_rsi import TrendRSIStrategy


def test_optimizer_finds_params_and_writes_report(tmp_path) -> None:
    rows = 280
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

    optimizer = ParameterOptimizer(5, 100, 20, report_dir=tmp_path)
    result = optimizer.optimize(
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
        keep_top_n=3,
    )

    assert result is not None
    assert result.strategy_name == "trend_rsi"
    assert result.best_params["rsi_period"] == 14
    assert result.selected_candidates
    assert len(result.selected_candidates) <= 3

    report_path = tmp_path / "trend_rsi_EURUSD_optimization_report.json"
    assert report_path.exists()

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["strategy"] == "trend_rsi"
    assert report["winning_parameter_sets"]


def test_optimizer_randomized_search_limits_trials() -> None:
    rows = 260
    prices = [1.0 + i * 0.00025 for i in range(rows)]
    candles = pd.DataFrame(
        {
            "open": prices,
            "high": [p + 0.0004 for p in prices],
            "low": [p - 0.0004 for p in prices],
            "close": prices,
            "volume": [100] * rows,
        }
    )

    optimizer = ParameterOptimizer(
        lookahead_bars=5,
        min_history_bars=100,
        step=20,
        search_method="randomized",
        random_search_trials=2,
    )
    result = optimizer.optimize(
        strategy=TrendRSIStrategy(),
        candles=candles,
        parameter_grid={
            "ema_fast": [8, 12, 20],
            "ema_slow": [30, 40, 50],
            "rsi_buy_threshold": [50, 55],
            "rsi_sell_threshold": [45],
        },
        symbol="EURUSD",
        fixed_params={"rsi_period": 14},
    )

    assert result is None or result.tested_combinations == 2
