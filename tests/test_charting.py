from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from core.types import FinalRecommendation, SignalAction
from ui.charting import ChartControls, prepare_chart_payload


def _candles(rows: int = 120) -> pd.DataFrame:
    start = pd.Timestamp("2026-01-01T00:00:00Z")
    data = []
    price = 1.10
    for idx in range(rows):
        t = start + pd.Timedelta(minutes=5 * idx)
        open_ = price
        close = price + (0.0005 if idx % 2 == 0 else -0.0003)
        high = max(open_, close) + 0.0004
        low = min(open_, close) - 0.0004
        data.append({"time": t, "open": open_, "high": high, "low": low, "close": close, "volume": 100 + idx})
        price = close
    return pd.DataFrame(data)


def test_prepare_chart_payload_empty_state() -> None:
    payload = prepare_chart_payload(pd.DataFrame(), ChartControls())
    assert payload["status"] == "empty"
    assert "No MT5 market data available" in payload["reason"]


def test_prepare_chart_payload_builds_indicators_and_markers() -> None:
    rec = FinalRecommendation(
        symbol="EURUSD",
        timeframe="M5",
        action=SignalAction.BUY,
        market_price=1.12,
        entry=1.119,
        stop_loss=1.117,
        take_profit=1.124,
        risk_reward=2.5,
        confidence=0.74,
        selected_strategy="trend_rsi",
        market_status="open",
        news_status="clear",
        signal_strength="strong",
        reasons=["trend support"],
        timestamp=datetime(2026, 1, 1, 4, 0, tzinfo=timezone.utc),
    )
    paper = pd.DataFrame(
        [
            {
                "symbol": "EURUSD",
                "timeframe": "M5",
                "entry": 1.1010,
                "exit_price": 1.1030,
                "outcome": "WIN",
                "is_win": True,
                "open_time": "2026-01-01T01:00:00Z",
                "close_time": "2026-01-01T01:45:00Z",
            }
        ]
    )
    news = [{"event_time": "2026-01-01T05:00:00Z", "title": "NFP", "impact": "high", "currency": "USD"}]

    payload = prepare_chart_payload(_candles(), ChartControls(show_sessions=True, show_support_resistance=True, show_volatility_zones=True), recommendation=rec, paper_trades=paper, news_events=news)

    assert payload["status"] == "ok"
    frame = payload["candles"]
    for col in ["ema_fast", "ema_slow", "rsi", "atr", "support", "resistance"]:
        assert col in frame.columns
    assert not payload["trade_markers"].empty
    assert not payload["news_markers"].empty
    assert payload["session_windows"]


def test_prepare_chart_payload_no_trade_note() -> None:
    rec = FinalRecommendation(
        symbol="EURUSD",
        timeframe="M5",
        action=SignalAction.NO_TRADE,
        market_price=1.12,
        entry=0.0,
        stop_loss=0.0,
        take_profit=0.0,
        risk_reward=0.0,
        confidence=0.0,
        selected_strategy="none",
        market_status="closed",
        news_status="clear",
        rejection_reason="Market closed",
        reasons=["closed"],
    )
    payload = prepare_chart_payload(_candles(), ChartControls(), recommendation=rec)
    assert payload["context"]["note"].startswith("NO_TRADE")
