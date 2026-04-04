from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from core.types import FinalRecommendation, SignalAction
from ui.terminal_view_model import (
    prepare_alert_rows,
    prepare_live_update_state,
    prepare_recommendation_panel,
    prepare_status_strip,
    prepare_watchlist_rows,
)


def _rec(action: SignalAction = SignalAction.BUY) -> FinalRecommendation:
    return FinalRecommendation(
        symbol="EURUSD",
        timeframe="M5",
        action=action,
        market_price=1.1,
        entry=1.101,
        stop_loss=1.099,
        take_profit=1.105,
        risk_reward=2.0,
        confidence=0.75,
        selected_strategy="trend_rsi",
        market_status="open",
        news_status="clear",
        signal_strength="strong",
        reasons=["Trend aligned"],
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_prepare_live_update_state_enforces_minimum_interval() -> None:
    state = prepare_live_update_state({}, symbol="EURUSD", timeframe="M1", refresh_interval=1, watch_mode=True, auto_refresh=True, compact_mode=False, expanded_chart=True)
    assert state.refresh_interval == 3
    assert state.watch_mode is True


def test_prepare_watchlist_rows_merges_snapshots_and_recommendations() -> None:
    snapshots = {"EURUSD": {"last_price": 1.1, "daily_change_pct": 0.2, "market_status": "open"}}
    rows = prepare_watchlist_rows(["EURUSD", "XAUUSD"], snapshots, {"EURUSD": _rec()})
    assert len(rows) == 2
    assert rows.loc[0, "latest_action"] == "BUY"
    assert rows.loc[1, "latest_action"] == "NO_TRADE"


def test_prepare_status_strip_contains_terminal_fields() -> None:
    fields = dict(
        prepare_status_strip(
            active_symbol="EURUSD",
            timeframe="M5",
            spread=0.8,
            session="london",
            market_status="open",
            news_status="clear",
            selected_strategy="trend_rsi",
            signal_strength="strong",
            current_price=1.12345,
        )
    )
    assert fields["Symbol"].startswith("EURUSD")
    assert fields["Signal"] == "STRONG"


def test_prepare_recommendation_panel_blocked_state() -> None:
    panel = prepare_recommendation_panel(_rec(SignalAction.NO_TRADE))
    assert panel["blocked"] is True
    assert panel["state"] == "blocked"


def test_prepare_recommendation_panel_includes_score_fields() -> None:
    recommendation = _rec()
    recommendation.historical_score = 70.0
    recommendation.recent_score = 62.0
    recommendation.combined_score = 66.4
    panel = prepare_recommendation_panel(recommendation)
    values = dict(panel["fields"])
    assert values["historical_score"] == "70.00"
    assert values["recent_score"] == "62.00"
    assert values["combined_score"] == "66.40"


def test_prepare_alert_rows_for_empty_and_populated_frames() -> None:
    assert prepare_alert_rows(pd.DataFrame()).empty
    frame = pd.DataFrame([
        {"timestamp": "2026-01-01T00:00:00Z", "symbol": "EURUSD", "status": "suppressed", "reason": "cooldown", "suppressed": True}
    ])
    rows = prepare_alert_rows(frame)
    assert rows.loc[0, "reason"] == "cooldown"
