from __future__ import annotations

import pandas as pd

from learning.historical_validation import HistoricalValidationPipeline, format_historical_results
from strategy.trend_rsi import TrendRSIStrategy


def test_historical_validation_pipeline_metrics_and_rank() -> None:
    rows = 420
    prices = [1.0 + i * 0.0002 for i in range(rows)]
    candles = pd.DataFrame(
        {
            "open": prices,
            "high": [p + 0.0005 for p in prices],
            "low": [p - 0.0005 for p in prices],
            "close": prices,
            "volume": [100] * rows,
        }
    )

    pipeline = HistoricalValidationPipeline(
        lookahead_bars=5,
        step=15,
        min_train_bars=120,
        validation_bars=60,
        rolling_step=30,
    )
    out = pipeline.evaluate_strategy(
        symbol="EURUSD",
        timeframe="M5",
        strategy=TrendRSIStrategy(),
        candles=candles,
        params={"ema_fast": 8, "ema_slow": 34, "rsi_period": 14, "rsi_buy_threshold": 55, "rsi_sell_threshold": 45},
    )

    assert out
    assert out["total_trades"] >= 0
    assert "score" in out
    assert "final_validation_score" in out
    assert "avg_reward_risk" in out
    assert "explainability" in out

    alt = dict(out)
    alt["strategy"] = "trend_rsi_alt"
    alt["score"] = float(out["score"]) - 1.0
    alt["final_validation_score"] = alt["score"]
    ranked = format_historical_results([out, alt])
    assert ranked.iloc[0]["rank"] == 1
    assert ranked.iloc[1]["rank"] == 2
