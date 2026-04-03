from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from core.types import NewsEvent
from core.types import SignalAction, StrategyScore, StrategySignal
from news.filter import NewsFilter
from learning.optimizer import OptimizationResult
from recommendation.engine import RecommendationEngine


@dataclass
class _Dummy:
    pass


class _FakeOptimizer:
    def optimize(self, *args, **kwargs):
        return None


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
    assert rec.selected_strategy == "trend_rsi"
    assert rec.news_status == "clear"
    assert rec.market_price == 1.251
    assert rec.timestamp == timestamp
    assert rec.risk_reward > 0
    assert any("excluded due to weak recent performance" in reason for reason in rec.reasons)


def test_format_for_terminal_contains_core_fields() -> None:
    engine = _engine()
    rec = engine._no_trade(
        "EURUSD",
        "M5",
        "News effect: High-impact news window",
        "blocked",
        "closed",
        datetime.utcnow(),
        1.1,
    )

    formatted = engine.format_for_terminal(rec)

    assert "FINAL RECOMMENDATION" in formatted
    assert "Market Status" in formatted
    assert "Symbol            :" in formatted
    assert "Timeframe         :" in formatted
    assert "Timestamp (UTC)" in formatted
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


class _FakeMT5:
    def __init__(self, market_status: str, reason: str = "") -> None:
        self.market_status = market_status
        self.reason = reason or market_status
        self.connected = True
        self.status_message = reason

    def connect(self) -> bool:
        self.connected = self.market_status != "mt5_unavailable"
        if not self.connected:
            self.status_message = "MT5 unavailable"
        return self.connected

    def detect_market_status(self, symbol: str, timeframe: str) -> tuple[str, str]:
        return self.market_status, self.reason

    def get_ohlcv(self, symbol: str, timeframe: str, bars: int) -> pd.DataFrame:
        now = pd.Timestamp.utcnow()
        return pd.DataFrame(
            [
                {"time": now, "open": 1.1, "high": 1.11, "low": 1.09, "close": 1.105, "volume": 100},
                {"time": now, "open": 1.105, "high": 1.12, "low": 1.1, "close": 1.11, "volume": 100},
            ]
        )

    def now(self) -> datetime:
        return datetime.utcnow()

    def shutdown(self) -> None:
        return None


class _FakeProvider:
    def fetch_events(self, from_time: datetime, to_time: datetime) -> list[NewsEvent]:
        return []


def _build_engine_with_market_status(status: str, reason: str = "") -> RecommendationEngine:
    return RecommendationEngine(
        mt5_client=_FakeMT5(status, reason),
        news_provider=_FakeProvider(),
        news_filter=NewsFilter(30, 15),
        strategies=[],
        settings={"app.data_bars": 50, "learning.optimization_enabled": False},
        optimizer=_FakeOptimizer(),
    )


def test_generate_market_open_status() -> None:
    engine = _build_engine_with_market_status("open", "market is open")
    signal = StrategySignal("test_strategy", SignalAction.BUY, 1.11, 1.1, 1.13, 0.75, ["trend up"])
    engine._run_strategies = lambda symbol, candles: [(signal, None)]  # type: ignore[method-assign]

    rec = engine.generate("EURUSD", "M5")

    assert rec.market_status == "open"
    assert rec.action == SignalAction.BUY
    assert rec.entry > 0
    assert rec.confidence > 0


def test_generate_market_closed_status_forces_no_trade() -> None:
    engine = _build_engine_with_market_status("closed", "session is closed")

    rec = engine.generate("EURUSD", "M5")

    assert rec.market_status == "closed"
    assert rec.action == SignalAction.NO_TRADE
    assert "market is closed" in rec.reasons[0].lower()
    assert rec.entry == 0.0
    assert rec.stop_loss == 0.0
    assert rec.take_profit == 0.0
    assert rec.confidence == 0.0


def test_generate_symbol_unavailable_market_status() -> None:
    engine = _build_engine_with_market_status("unavailable", "symbol missing")

    rec = engine.generate("BADSYMBOL", "M5")

    assert rec.market_status == "unavailable"
    assert rec.action == SignalAction.NO_TRADE


def test_generate_mt5_unavailable_market_status() -> None:
    engine = _build_engine_with_market_status("mt5_unavailable", "terminal unavailable")

    rec = engine.generate("EURUSD", "M5")

    assert rec.market_status == "mt5_unavailable"
    assert rec.action == SignalAction.NO_TRADE


def test_aggregate_forces_no_trade_when_market_not_open() -> None:
    engine = _engine()
    signal = StrategySignal("trend_rsi", SignalAction.BUY, 1.25, 1.24, 1.27, 0.8, ["trend aligned"])

    rec = engine._aggregate(
        "EURUSD",
        "M5",
        [(signal, None)],
        market_price=1.251,
        market_status="closed",
        news_status="clear",
    )

    assert rec.action == SignalAction.NO_TRADE
    assert rec.market_status == "closed"
    assert rec.entry == 0.0


def test_aggregate_forces_no_trade_when_news_blocked() -> None:
    engine = _engine()
    signal = StrategySignal("trend_rsi", SignalAction.BUY, 1.25, 1.24, 1.27, 0.8, ["trend aligned"])

    rec = engine._aggregate(
        "EURUSD",
        "M5",
        [(signal, None)],
        market_price=1.251,
        market_status="open",
        news_status="blocked",
        news_reason="NFP blackout",
    )

    assert rec.action == SignalAction.NO_TRADE
    assert rec.news_status == "blocked"
    assert any("blocked trading" in reason.lower() for reason in rec.reasons)


def test_final_recommendation_has_operator_output_fields() -> None:
    engine = _engine()
    signal = StrategySignal("trend_rsi", SignalAction.BUY, 1.25, 1.24, 1.27, 0.8, ["trend aligned"])
    rec = engine._aggregate("EURUSD", "M5", [(signal, None)], market_price=1.251)

    assert set(rec.__dataclass_fields__.keys()) == {
        "symbol",
        "timeframe",
        "action",
        "market_price",
        "entry",
        "stop_loss",
        "take_profit",
        "risk_reward",
        "confidence",
        "selected_strategy",
        "market_status",
        "news_status",
        "reasons",
        "timestamp",
    }
