"""Chart preparation and rendering helpers for Streamlit market visuals."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from core.indicators import atr, ema, rsi
from core.types import FinalRecommendation, SignalAction


@dataclass(slots=True)
class ChartControls:
    candles: int = 250
    show_ema_fast: bool = True
    show_ema_slow: bool = True
    show_breakout_levels: bool = True
    show_paper_trades: bool = True
    show_recommendation: bool = True
    show_sessions: bool = False
    show_news: bool = True
    show_support_resistance: bool = False
    show_volatility_zones: bool = False
    show_volume: bool = True
    expanded_mode: bool = False
    ema_fast_period: int = 9
    ema_slow_period: int = 21
    breakout_window: int = 20


def _coerce_time(frame: pd.DataFrame) -> pd.Series:
    if "time" not in frame.columns:
        return pd.Series(dtype="datetime64[ns, UTC]")
    return pd.to_datetime(frame["time"], utc=True, errors="coerce")


def _empty_payload(reason: str) -> dict[str, Any]:
    return {
        "status": "empty",
        "reason": reason,
        "candles": pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"]),
        "trade_markers": pd.DataFrame(columns=["time", "price", "label", "kind", "color", "symbol"]),
        "news_markers": pd.DataFrame(columns=["time", "title", "impact", "currency"]),
        "session_windows": [],
        "volatility_zones": [],
        "context": {},
        "has_volume": False,
    }


def prepare_chart_payload(
    candles: pd.DataFrame,
    controls: ChartControls,
    recommendation: FinalRecommendation | None = None,
    paper_trades: pd.DataFrame | None = None,
    news_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if candles is None or candles.empty:
        return _empty_payload("No MT5 market data available for selected symbol/timeframe.")

    required = {"time", "open", "high", "low", "close"}
    if not required.issubset(candles.columns):
        missing = sorted(required - set(candles.columns))
        return _empty_payload(f"Market data is missing required columns: {', '.join(missing)}")

    frame = candles.copy().tail(int(max(50, controls.candles))).reset_index(drop=True)
    frame["time"] = _coerce_time(frame)
    frame["ema_fast"] = ema(frame["close"], controls.ema_fast_period)
    frame["ema_slow"] = ema(frame["close"], controls.ema_slow_period)
    frame["rsi"] = rsi(frame["close"], 14)
    frame["atr"] = atr(frame, 14)

    if controls.show_breakout_levels:
        window = max(5, int(controls.breakout_window))
        frame["breakout_high"] = frame["high"].rolling(window=window, min_periods=window).max()
        frame["breakout_low"] = frame["low"].rolling(window=window, min_periods=window).min()

    if controls.show_support_resistance:
        swing = max(7, int(controls.breakout_window // 2))
        frame["support"] = frame["low"].rolling(window=swing, min_periods=swing).min()
        frame["resistance"] = frame["high"].rolling(window=swing, min_periods=swing).max()

    session_windows = _session_windows(frame) if controls.show_sessions else []
    volatility_zones = _volatility_zones(frame) if controls.show_volatility_zones else []
    trade_markers = _trade_markers(recommendation, paper_trades, controls.show_paper_trades, controls.show_recommendation)
    news_markers = _news_markers(news_events) if controls.show_news else pd.DataFrame(columns=["time", "title", "impact", "currency"])
    has_volume = "volume" in frame.columns and frame["volume"].notna().any()

    context = _build_trade_context(frame, recommendation)

    return {
        "status": "ok",
        "reason": "",
        "candles": frame,
        "trade_markers": trade_markers,
        "news_markers": news_markers,
        "session_windows": session_windows,
        "volatility_zones": volatility_zones,
        "context": context,
        "has_volume": has_volume,
    }


def _build_trade_context(candles: pd.DataFrame, recommendation: FinalRecommendation | None) -> dict[str, Any]:
    market_price = float(candles.iloc[-1]["close"]) if not candles.empty else 0.0
    if recommendation is None:
        return {
            "market_price": market_price,
            "entry_zone": "n/a",
            "stop_loss_distance": "n/a",
            "take_profit_distance": "n/a",
            "risk_reward": "n/a",
            "signal_strength": "n/a",
            "selected_strategy": "n/a",
            "note": "No recommendation yet. Chart still shows live market structure.",
        }

    sl_dist = abs(float(recommendation.entry) - float(recommendation.stop_loss)) if recommendation.stop_loss else 0.0
    tp_dist = abs(float(recommendation.take_profit) - float(recommendation.entry)) if recommendation.take_profit else 0.0
    entry_zone = f"{recommendation.entry:.5f}"

    return {
        "market_price": market_price,
        "entry_zone": entry_zone,
        "stop_loss_distance": f"{sl_dist:.5f}",
        "take_profit_distance": f"{tp_dist:.5f}",
        "risk_reward": f"{recommendation.risk_reward:.2f}",
        "signal_strength": recommendation.signal_strength,
        "selected_strategy": recommendation.selected_strategy,
        "note": _recommendation_note(recommendation),
    }


def _recommendation_note(recommendation: FinalRecommendation) -> str:
    if recommendation.action == SignalAction.NO_TRADE:
        if recommendation.market_status == "closed":
            return "NO_TRADE: market is currently closed."
        if recommendation.market_status == "mt5_unavailable":
            return "NO_TRADE: MT5 unavailable."
        if recommendation.news_status == "blocked":
            return "NO_TRADE: blocked by news filter."
        if recommendation.spread_state == "excessive":
            return "NO_TRADE: spread exceeds profile limits."
        return recommendation.rejection_reason or "NO_TRADE: filters did not pass minimum quality gates."
    return f"{recommendation.action} setup active."


def _trade_markers(
    recommendation: FinalRecommendation | None,
    paper_trades: pd.DataFrame | None,
    show_paper_trades: bool,
    show_recommendation: bool,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    if show_recommendation and recommendation is not None:
        ts = pd.Timestamp(recommendation.timestamp).tz_localize("UTC") if recommendation.timestamp.tzinfo is None else pd.Timestamp(recommendation.timestamp)
        action = recommendation.action.value if hasattr(recommendation.action, "value") else str(recommendation.action)
        color = "#00C853" if action == "BUY" else "#FF5252" if action == "SELL" else "#94a3b8"
        rows.append({"time": ts, "price": recommendation.entry or recommendation.market_price, "label": f"Latest {action}", "kind": "recommendation", "color": color, "symbol": "diamond"})
        if recommendation.stop_loss:
            rows.append({"time": ts, "price": recommendation.stop_loss, "label": "SL", "kind": "risk", "color": "#fb7185", "symbol": "line-ns-open"})
        if recommendation.take_profit:
            rows.append({"time": ts, "price": recommendation.take_profit, "label": "TP", "kind": "reward", "color": "#22c55e", "symbol": "line-ns-open"})

    if show_paper_trades and paper_trades is not None and not paper_trades.empty:
        trades = paper_trades.copy()
        open_col = "open_time" if "open_time" in trades.columns else None
        close_col = "close_time" if "close_time" in trades.columns else None
        if open_col:
            trades[open_col] = pd.to_datetime(trades[open_col], utc=True, errors="coerce")
        if close_col:
            trades[close_col] = pd.to_datetime(trades[close_col], utc=True, errors="coerce")
        for _, row in trades.tail(200).iterrows():
            win = bool(row.get("is_win", False)) or str(row.get("outcome", "")).upper() == "WIN"
            color = "#22c55e" if win else "#f97316"
            if open_col and pd.notna(row.get(open_col)):
                rows.append({"time": row[open_col], "price": float(row.get("entry", 0.0)), "label": "Paper Entry", "kind": "paper_entry", "color": color, "symbol": "triangle-up"})
            if close_col and pd.notna(row.get(close_col)):
                rows.append({"time": row[close_col], "price": float(row.get("exit_price", row.get("entry", 0.0))), "label": "Paper Exit", "kind": "paper_exit", "color": color, "symbol": "x"})

    return pd.DataFrame(rows)


def _news_markers(events: list[dict[str, Any]] | None) -> pd.DataFrame:
    if not events:
        return pd.DataFrame(columns=["time", "title", "impact", "currency"])
    rows: list[dict[str, Any]] = []
    for event in events:
        when = event.get("event_time") or event.get("time")
        stamp = pd.to_datetime(when, utc=True, errors="coerce")
        if pd.isna(stamp):
            continue
        rows.append(
            {
                "time": stamp,
                "title": str(event.get("title", "news event")),
                "impact": str(event.get("impact", "unknown")).lower(),
                "currency": str(event.get("currency", "")),
            }
        )
    return pd.DataFrame(rows)


def _session_windows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    windows: list[dict[str, Any]] = []
    labels = [
        (0, 8, "Asian", "rgba(30,64,175,0.10)"),
        (8, 13, "London", "rgba(8,145,178,0.10)"),
        (13, 22, "New York", "rgba(147,51,234,0.10)"),
    ]
    start = frame["time"].min().to_pydatetime()
    end = frame["time"].max().to_pydatetime()
    cursor = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    while cursor <= end + timedelta(days=1):
        for from_hour, to_hour, label, color in labels:
            w_start = cursor + timedelta(hours=from_hour)
            w_end = cursor + timedelta(hours=to_hour)
            if w_end < start or w_start > end:
                continue
            windows.append({"start": w_start, "end": w_end, "label": label, "color": color})
        cursor += timedelta(days=1)
    return windows


def _volatility_zones(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty or frame["atr"].dropna().empty:
        return []
    atr_series = frame[["time", "atr"]].dropna()
    threshold = atr_series["atr"].quantile(0.8)
    zones: list[dict[str, Any]] = []
    active_start = None
    for _, row in atr_series.iterrows():
        if float(row["atr"]) >= float(threshold):
            if active_start is None:
                active_start = row["time"]
        elif active_start is not None:
            zones.append({"start": active_start, "end": row["time"], "color": "rgba(245,158,11,0.14)", "label": "High volatility"})
            active_start = None
    if active_start is not None:
        zones.append({"start": active_start, "end": atr_series.iloc[-1]["time"], "color": "rgba(245,158,11,0.14)", "label": "High volatility"})
    return zones


def build_market_figure(payload: dict[str, Any], controls: ChartControls):
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except Exception as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(f"Plotly is required for chart rendering: {exc}") from exc

    frame = payload["candles"]
    show_volume_panel = controls.show_volume and bool(payload.get("has_volume", False))
    if show_volume_panel:
        fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.02, row_heights=[0.58, 0.12, 0.15, 0.15], subplot_titles=("Price", "Volume", "RSI (14)", "ATR (14)"))
        rsi_row, atr_row = 3, 4
    else:
        fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.62, 0.19, 0.19], subplot_titles=("Price", "RSI (14)", "ATR (14)"))
        rsi_row, atr_row = 2, 3

    fig.add_trace(
        go.Candlestick(
            x=frame["time"],
            open=frame["open"],
            high=frame["high"],
            low=frame["low"],
            close=frame["close"],
            name="Candles",
            increasing_line_color="#00e676",
            decreasing_line_color="#ff5252",
            increasing_fillcolor="#00c853",
            decreasing_fillcolor="#d50000",
            whiskerwidth=0.2,
        ),
        row=1,
        col=1,
    )

    if controls.show_ema_fast:
        fig.add_trace(go.Scatter(x=frame["time"], y=frame["ema_fast"], name=f"EMA {controls.ema_fast_period}", line={"color": "#00d4ff", "width": 1.6}), row=1, col=1)
    if controls.show_ema_slow:
        fig.add_trace(go.Scatter(x=frame["time"], y=frame["ema_slow"], name=f"EMA {controls.ema_slow_period}", line={"color": "#ffd166", "width": 1.6}), row=1, col=1)

    if controls.show_breakout_levels and "breakout_high" in frame.columns:
        fig.add_trace(go.Scatter(x=frame["time"], y=frame["breakout_high"], name="Breakout High", line={"color": "#9d4edd", "dash": "dot", "width": 1.2}), row=1, col=1)
        fig.add_trace(go.Scatter(x=frame["time"], y=frame["breakout_low"], name="Breakout Low", line={"color": "#c77dff", "dash": "dot", "width": 1.2}), row=1, col=1)

    if controls.show_support_resistance and "support" in frame.columns:
        fig.add_trace(go.Scatter(x=frame["time"], y=frame["support"], name="Support", line={"color": "#00e676", "dash": "dash", "width": 1}), row=1, col=1)
        fig.add_trace(go.Scatter(x=frame["time"], y=frame["resistance"], name="Resistance", line={"color": "#ff9100", "dash": "dash", "width": 1}), row=1, col=1)

    markers = payload["trade_markers"]
    if not markers.empty:
        fig.add_trace(
            go.Scatter(
                x=markers["time"],
                y=markers["price"],
                text=markers["label"],
                mode="markers+text",
                textposition="top center",
                name="Signals",
                marker={"size": 10, "symbol": markers["symbol"], "color": markers["color"], "line": {"color": "#e2e8f0", "width": 0.7}},
            ),
            row=1,
            col=1,
        )

    if controls.show_news and not payload["news_markers"].empty:
        events = payload["news_markers"].copy()
        events["y"] = frame["high"].max()
        events["hover"] = events["impact"].str.upper() + " | " + events["currency"] + " | " + events["title"]
        event_colors = events["impact"].map({"high": "#ff1744", "red": "#ff1744", "medium": "#ff9100", "orange": "#ff9100"}).fillna("#29b6f6")
        fig.add_trace(go.Scatter(x=events["time"], y=events["y"], mode="markers", marker={"symbol": "diamond", "size": 9, "color": event_colors}, text=events["hover"], name="News", hovertemplate="%{text}<extra></extra>"), row=1, col=1)

    if show_volume_panel:
        rising = frame["close"] >= frame["open"]
        colors = rising.map({True: "rgba(0,230,118,0.5)", False: "rgba(255,82,82,0.5)"})
        fig.add_trace(go.Bar(x=frame["time"], y=frame["volume"], name="Volume", marker={"color": colors}), row=2, col=1)

    fig.add_trace(go.Scatter(x=frame["time"], y=frame["rsi"], name="RSI", line={"color": "#4cc9f0", "width": 1.8}), row=rsi_row, col=1)
    fig.add_hline(y=70, row=rsi_row, col=1, line_width=1, line_color="#ff6b6b", line_dash="dash")
    fig.add_hline(y=30, row=rsi_row, col=1, line_width=1, line_color="#80ed99", line_dash="dash")
    fig.add_trace(go.Scatter(x=frame["time"], y=frame["atr"], name="ATR", line={"color": "#ffbe0b", "width": 1.8}), row=atr_row, col=1)

    for window in payload["session_windows"] + payload["volatility_zones"]:
        fig.add_vrect(x0=window["start"], x1=window["end"], fillcolor=window["color"], opacity=0.25, line_width=0, row=1, col=1)

    fig.update_layout(
        height=1040 if controls.expanded_mode else 900,
        dragmode="pan",
        margin={"t": 42, "r": 12, "b": 18, "l": 12},
        template="plotly_dark",
        paper_bgcolor="#060b16",
        plot_bgcolor="#0b1321",
        hovermode="x unified",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.01, "x": 0.0, "bgcolor": "rgba(6,11,22,0.78)", "font": {"size": 11}},
        xaxis_rangeslider_visible=False,
        font={"family": "Inter, Segoe UI, sans-serif", "size": 12},
    )
    fig.update_xaxes(showgrid=True, gridcolor="rgba(148,163,184,0.18)", zeroline=False)
    fig.update_yaxes(showgrid=True, gridcolor="rgba(148,163,184,0.15)", zeroline=False)
    fig.update_yaxes(title_text="Price", row=1, col=1)
    if show_volume_panel:
        fig.update_yaxes(title_text="Volume", row=2, col=1)
    fig.update_yaxes(title_text="RSI", row=rsi_row, col=1, range=[0, 100])
    fig.update_yaxes(title_text="ATR", row=atr_row, col=1)

    return fig
