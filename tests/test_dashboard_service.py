from __future__ import annotations

from datetime import datetime
import time

import pandas as pd
from core.types import FinalRecommendation, SignalAction
from ui import dashboard_service as dashboard_module
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


def test_recent_recommendations_handles_malformed_csv(tmp_path) -> None:
    service = DashboardService.__new__(DashboardService)
    service.recent_recommendations_path = tmp_path / "recent.csv"
    service.recent_recommendations_path.write_text('\"broken\nx,y,z', encoding="utf-8")

    frame = service.recent_recommendations(limit=10)
    assert frame.empty
    assert "symbol" in frame.columns
    assert "action" in frame.columns


def test_load_paper_trades_handles_empty_and_malformed_csv(tmp_path) -> None:
    service = DashboardService.__new__(DashboardService)
    service.trade_csv_path = tmp_path / "paper_trades.csv"
    service._trade_columns = [
        "strategy_name",
        "symbol",
        "side",
        "entry",
        "exit_price",
        "stop_loss",
        "take_profit",
        "open_time",
        "close_time",
        "outcome",
        "pnl",
        "is_win",
        "timeframe",
        "strategy",
        "result",
        "signal_strength",
        "market_conditions",
        "news_status",
        "spread_state",
        "session_state",
    ]

    empty = service.load_paper_trades(limit=10)
    assert empty.empty
    assert list(empty.columns) == service._trade_columns

    service.trade_csv_path.write_text('\"broken\nx,y,z', encoding="utf-8")
    malformed = service.load_paper_trades(limit=10)
    assert malformed.empty
    assert list(malformed.columns) == service._trade_columns


def test_fetch_historical_data_returns_success_payload(monkeypatch) -> None:
    class _FakeMT5:
        def __init__(self) -> None:
            self.status_message = "ok"

        def connect(self) -> bool:
            return True

        def shutdown(self) -> None:
            return None

    class _FakePipeline:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def fetch_and_store_days(self, *_args, **_kwargs):
            frame = pd.DataFrame(
                [
                    {"time": "2026-01-01T00:00:00+00:00", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 100},
                    {"time": "2026-01-02T00:00:00+00:00", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 100},
                ]
            )
            return frame, "data/market_history/EURUSD_M5.csv"

    monkeypatch.setattr(dashboard_module, "HistoricalDataPipeline", _FakePipeline)

    service = DashboardService.__new__(DashboardService)
    service.persistence = object()
    service._build_mt5_client = lambda: _FakeMT5()

    payload = service.fetch_historical_data("eurusd", "m5", 90)
    assert payload["success"] is True
    assert payload["candles_fetched"] == 2
    assert payload["symbol"] == "EURUSD"
    assert payload["timeframe"] == "M5"


def test_fetch_historical_data_invalid_lookback_payload(monkeypatch) -> None:
    class _FakeMT5:
        def __init__(self) -> None:
            self.status_message = "ok"

        def connect(self) -> bool:
            return True

        def shutdown(self) -> None:
            return None

    class _FakePipeline:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def fetch_and_store_days(self, *_args, **_kwargs):
            raise ValueError("Unsupported lookback window '10'.")

    monkeypatch.setattr(dashboard_module, "HistoricalDataPipeline", _FakePipeline)

    service = DashboardService.__new__(DashboardService)
    service.persistence = object()
    service._build_mt5_client = lambda: _FakeMT5()

    payload = service.fetch_historical_data("eurusd", "m5", 10)
    assert payload["success"] is False
    assert "Unsupported lookback window" in payload["status_message"]


def test_symbol_profile_summary_includes_profile_thresholds() -> None:
    service = DashboardService.__new__(DashboardService)
    service.settings = type(
        "S",
        (),
        {
            "get": lambda self, key, default=None: {
                "recommendation.symbol_profiles": {
                    "DEFAULT": {"spread_threshold": 25, "preferred_sessions": ["london"]},
                    "EURUSD": {"name": "eurusd_major", "min_confidence": 0.62, "spread_threshold": 18},
                }
            }.get(key, default)
        },
    )()
    summary = service.symbol_profile_summary("EURUSD")
    assert summary["name"] == "eurusd_major"
    assert summary["spread_threshold"] == 18.0
    assert summary["min_confidence"] == 0.62


def test_optimizer_leaderboard_by_symbol_reads_report(tmp_path) -> None:
    service = DashboardService.__new__(DashboardService)
    service.settings = type("S", (), {"get": lambda self, key, default=None: str(tmp_path) if key == "learning.optimization_report_dir" else default})()
    (tmp_path / "symbol_optimizer_leaderboard.json").write_text('[{"symbol":"EURUSD","strategy_name":"trend_rsi","best_score":2.1,"symbol_rank":1}]', encoding="utf-8")

    board = service.optimizer_leaderboard_by_symbol()
    assert not board.empty
    assert board.loc[0, "symbol"] == "EURUSD"


def test_evaluate_and_send_alert_suppresses_by_duplicate_history(tmp_path, monkeypatch) -> None:
    service = DashboardService.__new__(DashboardService)
    service.alert_state_path = tmp_path / "alert_state.json"
    service.alert_sent_history_path = tmp_path / "alert_sent_history.jsonl"
    service.settings = type(
        "S",
        (),
        {
            "get": lambda self, key, default=None: {
                "monitoring.minimum_confidence_for_alert": 0.6,
                "recommendation.min_confidence": 0.6,
                "recommendation.min_risk_reward": 1.5,
                "monitoring.minimum_signal_strength_for_alert": "strong",
                "monitoring.send_rejected_alerts": False,
                "monitoring.alert_cooldown_seconds": 1,
                "monitoring.alert_duplicate_window_seconds": 3600,
            }.get(key, default)
        },
    )()

    rec = FinalRecommendation(
        symbol="EURUSD",
        timeframe="M5",
        action=SignalAction.BUY,
        market_price=1.1,
        entry=1.1,
        stop_loss=1.09,
        take_profit=1.12,
        risk_reward=2.0,
        confidence=0.8,
        selected_strategy="trend_rsi",
        market_status="open",
        news_status="clear",
        signal_strength="strong",
        reasons=["ok"],
        timestamp=datetime(2026, 1, 1),
    )

    class _FakeNotifier:
        def send_recommendation_alert(self, recommendation, alert_type="strong_trade_alert"):
            return True, "sent"

    monkeypatch.setattr(dashboard_module.TelegramNotifier, "from_settings", lambda _settings: _FakeNotifier())

    first = service.evaluate_and_send_alert(rec)
    time.sleep(1.05)
    second = service.evaluate_and_send_alert(rec)

    assert first[0] == "sent"
    assert second[0] == "suppressed"
    assert second[1] == "duplicate_suppressed_by_history"
