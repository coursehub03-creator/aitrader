from datetime import datetime

from core.types import PaperTradeResult
from learning.evaluator import PerformanceEvaluator


def test_evaluator_outputs_scores() -> None:
    now = datetime.utcnow()
    results = [
        PaperTradeResult("trend_rsi", "EURUSD", "BUY", 1.0, 1.1, 0.95, 1.1, now, now, "WIN", 0.1, True),
        PaperTradeResult("trend_rsi", "EURUSD", "BUY", 1.1, 1.08, 1.05, 1.15, now, now, "LOSS", -0.02, False),
        PaperTradeResult("breakout_atr", "EURUSD", "SELL", 1.2, 1.1, 1.3, 1.1, now, now, "WIN", 0.1, True),
        PaperTradeResult("breakout_atr", "EURUSD", "SELL", 1.1, 1.0, 1.2, 1.0, now, now, "WIN", 0.1, True),
        PaperTradeResult("breakout_atr", "EURUSD", "SELL", 1.0, 1.1, 1.1, 0.9, now, now, "LOSS", -0.1, False),
        PaperTradeResult("breakout_atr", "EURUSD", "SELL", 1.3, 1.2, 1.4, 1.2, now, now, "WIN", 0.1, True),
        PaperTradeResult("breakout_atr", "EURUSD", "SELL", 1.4, 1.3, 1.5, 1.3, now, now, "WIN", 0.1, True),
    ]
    scores = PerformanceEvaluator(min_trades=2, max_drawdown_limit=1.0).evaluate(results)
    assert len(scores) == 2
    assert scores[0].score >= scores[1].score
    assert scores[0].trades >= 2
    assert scores[0].loss_rate >= 0.0
    assert scores[0].expectancy == scores[0].average_pnl


def test_evaluator_excludes_low_sample_or_high_drawdown() -> None:
    now = datetime.utcnow()
    results = [
        PaperTradeResult("few_trades", "EURUSD", "BUY", 1.0, 1.1, 0.9, 1.1, now, now, "WIN", 0.1, True),
        PaperTradeResult("risky", "EURUSD", "BUY", 1.1, 0.7, 1.0, 1.2, now, now, "LOSS", -0.4, False),
        PaperTradeResult("risky", "EURUSD", "BUY", 1.0, 1.05, 0.9, 1.1, now, now, "WIN", 0.05, True),
        PaperTradeResult("risky", "EURUSD", "BUY", 1.05, 1.0, 0.95, 1.15, now, now, "LOSS", -0.05, False),
        PaperTradeResult("risky", "EURUSD", "BUY", 1.08, 1.05, 0.98, 1.2, now, now, "LOSS", -0.03, False),
    ]
    scores = PerformanceEvaluator(min_trades=3, max_drawdown_limit=0.2).leaderboard(results)
    assert scores == []
