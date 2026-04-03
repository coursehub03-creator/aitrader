from datetime import datetime

from core.types import PaperTradeResult
from learning.evaluator import PerformanceEvaluator


def test_evaluator_outputs_scores() -> None:
    now = datetime.utcnow()
    results = [
        PaperTradeResult("trend_rsi", "EURUSD", "Buy", 1.0, 1.1, 0.1, True, now),
        PaperTradeResult("trend_rsi", "EURUSD", "Buy", 1.1, 1.08, -0.02, False, now),
        PaperTradeResult("breakout_atr", "EURUSD", "Sell", 1.2, 1.1, 0.1, True, now),
    ]
    scores = PerformanceEvaluator().evaluate(results)
    assert len(scores) == 2
    assert scores[0].score >= scores[1].score
