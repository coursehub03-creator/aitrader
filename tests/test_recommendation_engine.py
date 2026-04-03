from dataclasses import dataclass

from learning.optimizer import OptimizationResult
from recommendation.engine import RecommendationEngine


@dataclass
class _Dummy:
    pass


class _FakeOptimizer:
    pass


def _engine() -> RecommendationEngine:
    return RecommendationEngine(
        mt5_client=_Dummy(),
        news_provider=_Dummy(),
        news_filter=_Dummy(),
        strategies=[_Dummy(), _Dummy()],
        settings={},
        optimizer=_FakeOptimizer(),
    )


def test_active_strategy_names_respects_top_count_when_optimized() -> None:
    engine = _engine()
    ranked = {
        "s1": OptimizationResult("s1", {}, 2.0, 4, [], "r1"),
        "s2": OptimizationResult("s2", {}, 4.0, 4, [], "r2"),
        "s3": OptimizationResult("s3", {}, 1.0, 4, [], "r3"),
    }

    selected = engine._active_strategy_names(ranked, active_count=2, optimization_enabled=True)

    assert selected == {"s2", "s1"}


def test_active_strategy_names_falls_back_to_all_when_no_optimization() -> None:
    engine = _engine()
    engine.strategies = [type("S", (), {"name": "trend_rsi"})(), type("S", (), {"name": "breakout_atr"})()]

    selected = engine._active_strategy_names({}, active_count=2, optimization_enabled=False)

    assert selected == {"trend_rsi", "breakout_atr"}
