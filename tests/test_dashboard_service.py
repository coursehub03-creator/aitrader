from __future__ import annotations

from datetime import datetime

import pandas as pd

from core.types import FinalRecommendation, SignalAction
from ui.dashboard_service import DashboardService


class _FakeEngine:
    def __init__(self, recommendation: FinalRecommendation) -> None:
        self.recommendation = recommendation

    def generate(self, symbol: str, timeframe: str) -> FinalRecommendation:
        return self.recommendation


def test_recommendation_persistence_roundtrip(tmp_path) -> None:
    service = DashboardService.__new__(DashboardService)
    service.recent_recommendations_path = tmp_path / "recent.csv"

    rec = FinalRecommendation(
        symbol="EURUSD",
        timeframe="M5",
        action=SignalAction.BUY,
        market_price=1.1,
        entry=1.1,
        stop_loss=1.09,
        take_profit=1.12,
        risk_reward=2.0,
        confidence=0.75,
        selected_strategy="trend_rsi",
        market_status="open",
        news_status="clear",
        reasons=["trend aligned"],
        timestamp=datetime(2026, 1, 1),
    )

    service.persist_recommendation(rec)
    frame = service.recent_recommendations(limit=10)

    assert len(frame) == 1
    assert frame.loc[0, "symbol"] == "EURUSD"
    assert frame.loc[0, "action"] == "BUY"
    assert "trend aligned" in frame.loc[0, "reasons"]


def test_generate_recommendation_returns_no_trade_on_error(tmp_path) -> None:
    service = DashboardService.__new__(DashboardService)
    service.recent_recommendations_path = tmp_path / "recent.csv"

    class _ErrorEngine:
        def generate(self, symbol: str, timeframe: str):
            raise RuntimeError("boom")

    service.engine = _ErrorEngine()

    rec = service.generate_recommendation("EURUSD", "M5")

    assert rec.action == SignalAction.NO_TRADE
    assert rec.market_status == "mt5_unavailable"
    assert rec.news_status == "unknown"
    assert "Runtime error" in rec.reasons[0]


def test_alert_history_recording(tmp_path) -> None:
    service = DashboardService.__new__(DashboardService)
    service.alert_history_path = tmp_path / "alerts.csv"

    rec = FinalRecommendation(
        symbol="EURUSD",
        timeframe="M5",
        action=SignalAction.BUY,
        market_price=1.1,
        entry=1.1,
        stop_loss=1.09,
        take_profit=1.12,
        risk_reward=2.0,
        confidence=0.75,
        selected_strategy="trend_rsi",
        market_status="open",
        news_status="clear",
        reasons=["trend aligned"],
        timestamp=datetime(2026, 1, 1),
    )

    service.persist_alert_event(
        rec,
        status="suppressed",
        reason="duplicate_suppressed_by_cooldown",
        triggered=False,
        alert_type="strong_trade_alert",
    )
    frame = service.recent_alert_events(limit=10)
    assert len(frame) == 1
    assert frame.loc[0, "symbol"] == "EURUSD"
    assert frame.loc[0, "timeframe"] == "M5"
    assert frame.loc[0, "alert_type"] == "strong_trade_alert"
    assert bool(frame.loc[0, "suppressed"]) is True
