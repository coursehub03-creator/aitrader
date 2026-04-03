"""Data preparation layer for terminal-style dashboard panels."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from core.types import FinalRecommendation


@dataclass(slots=True)
class LiveUpdateState:
    symbol: str
    timeframe: str
    refresh_interval: int
    watch_mode: bool
    auto_refresh: bool
    compact_mode: bool
    expanded_chart: bool


def prepare_live_update_state(previous: dict[str, Any], *, symbol: str, timeframe: str, refresh_interval: int, watch_mode: bool, auto_refresh: bool, compact_mode: bool, expanded_chart: bool) -> LiveUpdateState:
    return LiveUpdateState(
        symbol=symbol or previous.get("symbol", "EURUSD"),
        timeframe=timeframe or previous.get("timeframe", "M5"),
        refresh_interval=max(3, int(refresh_interval or previous.get("refresh_interval", 10))),
        watch_mode=bool(watch_mode),
        auto_refresh=bool(auto_refresh),
        compact_mode=bool(compact_mode),
        expanded_chart=bool(expanded_chart),
    )


def prepare_watchlist_rows(symbols: list[str], snapshots: dict[str, dict[str, Any]], recommendations: dict[str, FinalRecommendation]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        snap = snapshots.get(symbol, {})
        rec = recommendations.get(symbol)
        action = "NO_TRADE" if rec is None else str(getattr(rec.action, "value", rec.action))
        signal = "n/a" if rec is None else str(rec.signal_strength).upper()
        rows.append(
            {
                "symbol": symbol,
                "last_price": float(snap.get("last_price", 0.0)),
                "daily_change_pct": float(snap.get("daily_change_pct", 0.0)),
                "market_status": str(snap.get("market_status", "unknown")),
                "latest_action": action,
                "signal_strength": signal,
            }
        )
    return pd.DataFrame(rows)


def prepare_status_strip(*, active_symbol: str, timeframe: str, spread: float, session: str, market_status: str, news_status: str, selected_strategy: str, signal_strength: str, current_price: float) -> list[tuple[str, str]]:
    return [
        ("Symbol", f"{active_symbol} ({timeframe})"),
        ("Price", f"{current_price:.5f}"),
        ("Spread", f"{spread:.2f}"),
        ("Session", session),
        ("Market", market_status),
        ("News", news_status),
        ("Strategy", selected_strategy),
        ("Signal", signal_strength.upper()),
    ]


def prepare_recommendation_panel(recommendation: FinalRecommendation | None) -> dict[str, Any]:
    if recommendation is None:
        return {"state": "no_data", "title": "No recommendation", "blocked": False, "fields": [], "reasons": []}

    action = str(getattr(recommendation.action, "value", recommendation.action))
    blocked = action == "NO_TRADE"
    state = "blocked" if blocked else "active"
    return {
        "state": state,
        "title": action,
        "blocked": blocked,
        "fields": [
            ("entry", f"{recommendation.entry:.5f}"),
            ("stop_loss", f"{recommendation.stop_loss:.5f}"),
            ("take_profit", f"{recommendation.take_profit:.5f}"),
            ("confidence", f"{recommendation.confidence:.2%}"),
            ("risk_reward", f"{recommendation.risk_reward:.2f}"),
            ("signal_strength", recommendation.signal_strength.upper()),
            ("selected_strategy", recommendation.selected_strategy),
        ],
        "reasons": recommendation.reasons,
        "rejection_reason": recommendation.rejection_reason or "",
    }


def prepare_alert_rows(alert_events: pd.DataFrame, limit: int = 20) -> pd.DataFrame:
    if alert_events.empty:
        return pd.DataFrame(columns=["timestamp", "symbol", "status", "reason", "suppressed"])
    frame = alert_events.copy().tail(limit)
    keep = [col for col in ["timestamp", "symbol", "status", "reason", "suppressed", "suppression_reason"] if col in frame.columns]
    return frame[keep].iloc[::-1].reset_index(drop=True)


def utc_now_label() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
