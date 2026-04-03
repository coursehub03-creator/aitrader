from dataclasses import dataclass
from datetime import datetime

from core.types import NewsEvent
from core.types import SignalAction, StrategyScore, StrategySignal
from news.filter import NewsFilter
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


def test_aggregate_excludes_very_weak_strategies() -> None:
    engine = _engine()
    engine.settings = {
        "learning.weak_strategy_score_cutoff": 1.0,
        "learning.weak_strategy_confidence_multiplier": 0.5,
    }
    timestamp = datetime.utcnow()
    strong = StrategySignal("trend_rsi", SignalAction.BUY, 1.25, 1.24, 1.27, 0.8, ["trend aligned"])
    weak = StrategySignal("breakout_atr", SignalAction.BUY, 1.26, 1.245, 1.275, 0.7, ["weak breakout"])

    rec = engine._aggregate(
        "EURUSD",
        "M5",
        [
            (strong, StrategyScore("trend_rsi", 5.0, 0.0, 10, 1.0, 0.6, 0.4, 0.1, 1.2, 0.1)),
            (weak, StrategyScore("breakout_atr", 0.0, -1.0, 10, 1.0, 0.3, 0.7, -0.1, 0.6, -0.1)),
        ],
        market_price=1.251,
        confidence_multiplier=1.0,
        news_status="clear",
        timestamp=timestamp,
    )

    assert rec.final_action == SignalAction.BUY
    assert rec.strategy_name == "trend_rsi"
    assert rec.selected_strategy_name == "trend_rsi"
    assert rec.news_status == "clear"
    assert rec.market_price == 1.251
    assert rec.timestamp == timestamp
    assert rec.risk_reward_ratio > 0
    assert any("excluded due to weak recent performance" in reason for reason in rec.reasons)


def test_format_for_terminal_contains_core_fields() -> None:
    engine = _engine()
    rec = engine._no_trade("EURUSD", "M5", "News effect: High-impact news window", "blocked", datetime.utcnow(), 1.1)

    formatted = engine.format_for_terminal(rec)

    assert "FINAL RECOMMENDATION" in formatted
    assert "Action            :" in formatted
    assert "News Status" in formatted
    assert "REASONS" in formatted
    assert "Market Price" in formatted
    assert "Selected Strategy" in formatted
    assert "News Effect" in formatted


def test_news_gate_returns_unknown_when_provider_fails() -> None:
    engine = _engine()
    engine.settings = {"news.symbols_map": {}}
    engine.mt5 = type("MT5", (), {"now": lambda self: datetime.utcnow()})()
    engine.news_filter = NewsFilter(30, 15)

    class _BoomProvider:
        def fetch_events(self, from_time: datetime, to_time: datetime) -> list[NewsEvent]:
            raise RuntimeError("provider down")

    engine.news_provider = _BoomProvider()
    blocked, news_status, reason, confidence_multiplier = engine._news_gate("EURUSD")

    assert blocked is False
    assert news_status == "unknown"
    assert "unavailable" in reason
    assert confidence_multiplier == 1.0
