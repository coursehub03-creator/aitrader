"""Premium Streamlit operator dashboard for local recommendation workflows."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import traceback

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.types import FinalRecommendation, SignalAction
from monitoring.live_monitor import MonitorState, to_utc_label
from ui.charting import ChartControls, build_market_figure, prepare_chart_payload
from ui.dashboard_service import DashboardService
from ui.learning_center import build_learning_diagnostics
from ui.terminal_view_model import (
    prepare_alert_rows,
    prepare_live_update_state,
    prepare_recommendation_panel,
    prepare_status_strip,
    prepare_watchlist_rows,
    utc_now_label,
)

st.set_page_config(page_title="AITrader Trading Terminal", page_icon="📈", layout="wide")

COMMON_SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "AUDUSD", "USDCAD"]
TIMEFRAMES = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]
LOOKBACK_OPTIONS = [30, 90, 180, 365]

THEME_CSS = """
<style>
.main, [data-testid="stAppViewContainer"] { background: radial-gradient(circle at top, #10192b 0%, #060b16 48%, #02040b 100%); color:#e2e8f0; }
.block-container { max-width: 100% !important; padding: 0.65rem 0.9rem 1rem 0.9rem; }
.terminal-strip{display:flex;gap:.4rem;overflow-x:auto;padding:.35rem .2rem .5rem .2rem;}
.terminal-pill{background:#0d1526;border:1px solid #27344e;border-radius:10px;padding:.28rem .55rem;min-width:120px}
.terminal-k{font-size:.65rem;color:#8aa0c7;text-transform:uppercase;letter-spacing:.06em}
.terminal-v{font-size:.88rem;color:#f8fbff;font-weight:700}
.rec-card{border-radius:12px;padding:.7rem;background:#0f172a;border:1px solid #2b3a55}
.rec-active{box-shadow: inset 0 0 0 1px rgba(34,197,94,.45);}
.rec-blocked{box-shadow: inset 0 0 0 1px rgba(239,68,68,.45);}
.small-muted{font-size:.77rem;color:#94a3b8}
</style>
"""


@st.cache_resource
def get_service() -> DashboardService:
    return DashboardService()


@st.cache_data(ttl=25, show_spinner=False)
def _load_chart_candles(symbol: str, timeframe: str, bars: int) -> tuple[pd.DataFrame, str]:
    return get_service().refresh_market_data(symbol, timeframe, bars=bars)


@st.cache_data(ttl=75, show_spinner=False)
def _load_chart_news(symbol: str) -> list[dict]:
    return get_service().recent_news_events(symbol)


def ensure_state() -> None:
    defaults = {
        "selected_symbol": "EURUSD",
        "selected_timeframe": "M5",
        "last_recommendation": None,
        "recommendations_by_symbol": {},
        "last_refresh_label": "Never",
        "latest_alert_status": "n/a",
        "latest_alert_reason": "",
        "latest_alert_type": "n/a",
        "alert_suppressed_reason": "",
        "monitoring_state": "stopped",
        "watch_mode": False,
        "monitor_running": False,
        "monitor_cycle_id": 0,
        "monitor_next_refresh_label": "Never",
        "monitor_last_alert_label": "Never",
        "monitor_last_market_status": "unknown",
        "monitor_last_news_status": "unknown",
        "auto_refresh": True,
        "refresh_interval": 15,
        "compact_mode": False,
        "expanded_chart": False,
        "recommendation_history": [],
        "optimizer_output": pd.DataFrame(),
        "validation_output": pd.DataFrame(),
        "send_test_telegram": False,
        "last_telegram_test_time": "Never",
        "last_telegram_test_result": "n/a",
        "last_telegram_test_reason": "",
        "monitor_runtime": MonitorState(),
        "history_fetch_symbol": "EURUSD",
        "history_fetch_timeframe": "M5",
        "history_fetch_lookback_days": 90,
        "history_fetch_result": {},
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def normalize_recommendation(recommendation: FinalRecommendation) -> FinalRecommendation:
    if recommendation.market_status in {"mt5_unavailable", "closed"}:
        recommendation.action = SignalAction.NO_TRADE
    if recommendation.news_status == "blocked":
        recommendation.action = SignalAction.NO_TRADE
    return recommendation


def run_cycle(service: DashboardService, symbol: str, timeframe: str, watch_mode: bool) -> FinalRecommendation:
    st.session_state.monitor_cycle_id += 1
    cycle_id = int(st.session_state.monitor_cycle_id)
    recommendation, monitor_meta = service.run_monitor_cycle(symbol, timeframe, watch_mode=watch_mode, cycle_id=cycle_id)
    recommendation = normalize_recommendation(recommendation)
    st.session_state.last_recommendation = recommendation
    st.session_state.recommendations_by_symbol[symbol] = recommendation
    st.session_state.last_refresh_label = utc_now_label()
    st.session_state.recommendation_history = ([
        {
            "timestamp": recommendation.timestamp.replace(tzinfo=timezone.utc).isoformat(timespec="seconds"),
            "symbol": recommendation.symbol,
            "action": recommendation.action.value if hasattr(recommendation.action, "value") else str(recommendation.action),
            "confidence": recommendation.confidence,
            "signal_strength": recommendation.signal_strength,
            "selected_strategy": recommendation.selected_strategy,
            "market_status": recommendation.market_status,
            "news_status": recommendation.news_status,
        }
    ] + st.session_state.recommendation_history)[:200]

    st.session_state.latest_alert_status = monitor_meta["alert_status"]
    st.session_state.latest_alert_reason = monitor_meta["alert_reason"]
    st.session_state.latest_alert_type = monitor_meta["alert_type"]
    st.session_state.alert_suppressed_reason = (
        monitor_meta["alert_reason"] if monitor_meta["alert_status"] == "suppressed" else ""
    )
    st.session_state.monitor_last_market_status = monitor_meta["market_status"]
    st.session_state.monitor_last_news_status = monitor_meta["news_status"]
    return recommendation


def build_symbol_snapshot(service: DashboardService, symbol: str, timeframe: str) -> dict:
    candles, _ = service.refresh_market_data(symbol, timeframe, bars=180)
    market_status, _ = service.connection_status(symbol, timeframe)
    if candles.empty:
        return {"last_price": 0.0, "daily_change_pct": 0.0, "market_status": market_status}
    last = float(candles.iloc[-1]["close"])
    first = float(candles.iloc[0]["open"])
    change = ((last - first) / first) * 100 if first else 0.0
    return {"last_price": last, "daily_change_pct": change, "market_status": market_status}


def render_status_strip(recommendation: FinalRecommendation | None, symbol: str, timeframe: str, snapshots: dict[str, dict]) -> None:
    if recommendation:
        spread = recommendation.spread_value
        session = recommendation.session_state
        market_status = recommendation.market_status
        news_status = recommendation.news_status
        strategy = recommendation.selected_strategy
        signal = recommendation.signal_strength
    else:
        spread, session, market_status, news_status, strategy, signal = 0.0, "n/a", snapshots.get(symbol, {}).get("market_status", "unknown"), "unknown", "n/a", "weak"

    rows = prepare_status_strip(
        active_symbol=symbol,
        timeframe=timeframe,
        spread=spread,
        session=session,
        market_status=market_status,
        news_status=news_status,
        selected_strategy=strategy,
        signal_strength=signal,
        current_price=float(snapshots.get(symbol, {}).get("last_price", 0.0)),
    )
    status_cols = st.columns(len(rows), gap="small")
    for idx, (k, v) in enumerate(rows):
        status_cols[idx].metric(k, v)


def render_watchlist(service: DashboardService, symbols: list[str], timeframe: str, recommendations: dict[str, FinalRecommendation]) -> tuple[pd.DataFrame, dict[str, dict]]:
    snapshots = {sym: build_symbol_snapshot(service, sym, timeframe) for sym in symbols}
    rows = prepare_watchlist_rows(symbols, snapshots, recommendations)
    rows["daily_change_pct"] = rows["daily_change_pct"].map(lambda v: f"{v:+.2f}%")
    rows["last_price"] = rows["last_price"].map(lambda v: f"{v:.5f}" if v else "n/a")
    st.dataframe(rows, use_container_width=True, hide_index=True, height=295)
    return rows, snapshots


def render_chart(service: DashboardService, symbol: str, timeframe: str, recommendation: FinalRecommendation | None, expanded_chart: bool) -> None:
    c = st.columns(7)
    candles = int(c[0].number_input("Candles", min_value=120, max_value=1500, value=420, step=20))
    show_ema = c[1].toggle("EMA", value=True)
    show_breakout = c[2].toggle("Breakout", value=True)
    show_paper = c[3].toggle("Paper", value=True)
    show_news = c[4].toggle("News", value=True)
    show_sr = c[5].toggle("S/R", value=False)
    show_vol = c[6].toggle("Vol Zones", value=False)
    c2 = st.columns(4)
    show_sessions = c2[0].toggle("Sessions", value=True)
    show_volume = c2[1].toggle("Volume", value=True)
    show_recommendation = c2[2].toggle("Signal Overlay", value=True)
    breakout_window = int(c2[3].slider("Breakout Window", min_value=10, max_value=80, value=24, step=2))

    controls = ChartControls(
        candles=candles,
        show_ema_fast=show_ema,
        show_ema_slow=show_ema,
        show_breakout_levels=show_breakout,
        show_paper_trades=show_paper,
        show_recommendation=show_recommendation,
        show_sessions=show_sessions,
        show_news=show_news,
        show_support_resistance=show_sr,
        show_volatility_zones=show_vol,
        show_volume=show_volume,
        expanded_mode=expanded_chart,
        breakout_window=breakout_window,
    )

    candles_frame, market_msg = _load_chart_candles(symbol, timeframe, candles)
    if candles_frame.empty:
        st.error("MT5 candle feed unavailable. Keep MT5 open for live chart updates.")
        st.caption(f"Details: {market_msg}")
        return

    paper = service.load_paper_trades(limit=600)
    if not paper.empty:
        paper = paper[(paper["symbol"].astype(str) == symbol) & (paper["timeframe"].astype(str).str.upper() == timeframe.upper())]
    payload = prepare_chart_payload(candles_frame, controls, recommendation=recommendation, paper_trades=paper, news_events=_load_chart_news(symbol) if show_news else [])
    if payload["status"] != "ok":
        st.info(payload["reason"])
        return

    try:
        st.plotly_chart(build_market_figure(payload, controls), use_container_width=True, theme=None)
    except Exception as exc:  # pragma: no cover - defensive fallback for plot rendering
        st.warning("Chart rendering fallback activated. Live chart is unavailable right now.")
        st.caption(f"Details: {exc}")


def render_recommendation_panel(recommendation: FinalRecommendation | None) -> None:
    panel = prepare_recommendation_panel(recommendation)
    is_active = panel["state"] == "active"
    st.caption("Current Recommendation")
    if is_active:
        st.success(panel["title"])
    else:
        st.warning(panel["title"])
    for k, v in panel["fields"]:
        st.metric(k.replace("_", " ").title(), v)
    if panel.get("rejection_reason"):
        st.warning(panel["rejection_reason"])
    if panel["reasons"]:
        with st.expander("Reasons", expanded=True):
            for reason in panel["reasons"]:
                st.markdown(f"- {reason}")


def render_history_panel(service: DashboardService) -> None:
    recent_disk = service.recent_recommendations(limit=80)
    recent = pd.DataFrame(st.session_state.recommendation_history)
    merged = pd.concat([recent, recent_disk], ignore_index=True) if not recent.empty else recent_disk
    dedupe_cols = [col for col in ["timestamp", "symbol", "selected_strategy", "action"] if col in merged.columns]
    if dedupe_cols:
        merged = merged.drop_duplicates(subset=dedupe_cols, keep="first")
    st.dataframe(merged.head(120), use_container_width=True, hide_index=True, height=320)


def render_alerts_panel(service: DashboardService) -> None:
    alerts = prepare_alert_rows(service.recent_alert_events(limit=80), limit=80)
    summary = service.latest_alert_summary()
    top = st.columns(2, gap="small")
    top[0].metric("Last alert sent", summary["last_sent"])
    top[1].metric("Last alert suppressed", summary["last_suppressed"])
    st.caption(f"Last suppression reason: {summary['suppression_reason']}")
    st.dataframe(alerts if not alerts.empty else pd.DataFrame([{"info": "No alerts yet"}]), use_container_width=True, hide_index=True, height=320)
    st.caption(
        f"Telegram status: {st.session_state.latest_alert_status} | "
        f"type: {st.session_state.latest_alert_type} | "
        f"reason: {st.session_state.latest_alert_reason or 'n/a'}"
    )


def render_learning_health(payload: dict) -> None:
    health = payload["health"]
    m = st.columns(6)
    m[0].metric("Learning Health", str(health.get("status", "n/a")).upper())
    m[1].metric("Active Strategies", health.get("active_strategies", 0))
    m[2].metric("Candidates", health.get("candidate_strategies", 0))
    m[3].metric("Disabled", health.get("disabled_strategies", 0))
    m[4].metric("Last Optimization", health.get("last_optimization_run", "n/a"))
    m[5].metric("Last Validation", health.get("last_historical_validation_run", "n/a"))


def render_trading_cockpit(service: DashboardService, state, recommendation: FinalRecommendation | None) -> None:
    left_col, right_col = st.columns([1.05, 1.95], gap="small")
    with left_col:
        st.markdown("### Watchlist")
        _, snapshots = render_watchlist(service, COMMON_SYMBOLS, state.timeframe, st.session_state.recommendations_by_symbol)
        st.caption(f"Monitoring: {st.session_state.monitoring_state} • Last refresh: {st.session_state.last_refresh_label}")
        jump_a, jump_b = st.columns(2, gap="small")
        for idx, sym in enumerate(COMMON_SYMBOLS):
            target = jump_a if idx % 2 == 0 else jump_b
            if target.button(sym, key=f"jump_{sym}", use_container_width=True):
                st.session_state.selected_symbol = sym
                st.rerun()
    with right_col:
        render_status_strip(recommendation, state.symbol, state.timeframe, snapshots)
        summary_col, intel_col = st.columns([1.35, 1.0], gap="small")
        with summary_col:
            st.markdown("### Recommendation Summary")
            render_recommendation_panel(recommendation)
            if recommendation is not None:
                st.markdown("### Market / News Status")
                m = st.columns(4, gap="small")
                m[0].metric("Market Status", recommendation.market_status)
                m[1].metric("News Status", recommendation.news_status)
                m[2].metric("Spread State", recommendation.spread_state)
                m[3].metric("Session", recommendation.session_state)
        with intel_col:
            st.markdown("### Intelligence Panel")
            snap = snapshots.get(state.symbol, {"last_price": 0.0, "daily_change_pct": 0.0, "market_status": "unknown"})
            profile_summary = service.symbol_profile_summary(state.symbol)
            st.metric("Current Symbol", state.symbol)
            st.metric("Last Price", f"{float(snap.get('last_price', 0.0)):.5f}" if snap.get("last_price") else "n/a")
            st.metric("Daily Change", f"{float(snap.get('daily_change_pct', 0.0)):+.2f}%")
            st.metric("Market Snapshot", str(snap.get("market_status", "unknown")))
            st.metric("Alert Status", st.session_state.latest_alert_status)
            st.metric("Profile", str(profile_summary.get("name", "default")))
            st.caption(st.session_state.latest_alert_reason or "No alert reason available.")
            st.caption(
                "Profile gates — "
                f"Session: {','.join(profile_summary.get('preferred_sessions', [])) or 'any'} | "
                f"Spread≤{float(profile_summary.get('spread_threshold', 0.0)):.2f} | "
                f"MinConf {float(profile_summary.get('min_confidence', 0.0)):.2f} | "
                f"MinRR {float(profile_summary.get('min_risk_reward', 0.0)):.2f}"
            )
            if recommendation and recommendation.market_status == "mt5_unavailable":
                st.error("⚠️ MT5 unavailable: recommendations forced to NO_TRADE.")
            elif recommendation and recommendation.market_status == "closed":
                st.warning("🚫 Market closed for active symbol/timeframe.")
            elif recommendation and recommendation.market_status == "unknown":
                st.info("ℹ️ Market state unknown: safety filters are active.")

    recent_col, alerts_col = st.columns([1.45, 1.0], gap="small")
    with recent_col:
        st.markdown("### Recent Recommendation Summary")
        render_history_panel(service)
    with alerts_col:
        st.markdown("### Alerts Feed")
        render_alerts_panel(service)


def render_market_visuals(service: DashboardService, state, recommendation: FinalRecommendation | None) -> None:
    st.markdown("### Main Live Chart Workspace")
    render_chart(service, state.symbol, state.timeframe, recommendation, state.expanded_chart)

    markers_col, paper_col = st.columns([1.1, 0.9], gap="small")
    with markers_col:
        st.markdown("### Recommendation Markers")
        recent_disk = service.recent_recommendations(limit=120)
        if not recent_disk.empty:
            filtered = recent_disk[
                (recent_disk["symbol"].astype(str) == state.symbol)
            ]
        else:
            filtered = recent_disk
        st.dataframe(
            filtered if not filtered.empty else pd.DataFrame([{"info": "No recommendation markers yet"}]),
            use_container_width=True,
            hide_index=True,
            height=250,
        )
    with paper_col:
        st.markdown("### Paper Trade Markers")
        paper = service.load_paper_trades(limit=120)
        if not paper.empty:
            paper = paper[
                (paper["symbol"].astype(str) == state.symbol)
                & (paper["timeframe"].astype(str).str.upper() == state.timeframe.upper())
            ]
        st.dataframe(
            paper if not paper.empty else pd.DataFrame([{"info": "No paper trade markers yet"}]),
            use_container_width=True,
            hide_index=True,
            height=250,
        )


def render_self_learning_center(service: DashboardService) -> None:
    st.markdown("### Historical Learning Workflow")
    st.caption("Run end-to-end historical learning for a selected symbol/timeframe and inspect outcomes below.")

    controls = st.columns([1.0, 1.0, 1.0, 1.1, 1.15, 1.1], gap="small")
    st.session_state.history_fetch_symbol = controls[0].selectbox(
        "Symbol",
        COMMON_SYMBOLS,
        index=COMMON_SYMBOLS.index(st.session_state.history_fetch_symbol) if st.session_state.history_fetch_symbol in COMMON_SYMBOLS else 0,
        key="historical_learning_symbol",
    )
    st.session_state.history_fetch_timeframe = controls[1].selectbox(
        "Timeframe",
        TIMEFRAMES,
        index=TIMEFRAMES.index(st.session_state.history_fetch_timeframe) if st.session_state.history_fetch_timeframe in TIMEFRAMES else 1,
        key="historical_learning_timeframe",
    )
    st.session_state.history_fetch_lookback_days = controls[2].selectbox(
        "Lookback Range",
        LOOKBACK_OPTIONS,
        index=LOOKBACK_OPTIONS.index(int(st.session_state.history_fetch_lookback_days)) if int(st.session_state.history_fetch_lookback_days) in LOOKBACK_OPTIONS else 1,
        key="historical_learning_lookback",
    )
    fetch_clicked = controls[3].button("Fetch Historical Data", type="primary", use_container_width=True, key="fetch_historical_data_action")
    validate_clicked = controls[4].button("Run Historical Validation", use_container_width=True, key="run_historical_validation_action")
    optimize_clicked = controls[5].button("Run Symbol Optimizer", use_container_width=True, key="run_symbol_optimizer_action")

    if fetch_clicked:
        with st.spinner("Fetching historical candles from MT5..."):
            st.session_state.history_fetch_result = service.fetch_historical_data(
                st.session_state.history_fetch_symbol,
                st.session_state.history_fetch_timeframe,
                int(st.session_state.history_fetch_lookback_days),
            )
    if validate_clicked:
        with st.spinner("Running historical validation over stored history..."):
            st.session_state.validation_output = service.run_historical_validation()
    if optimize_clicked:
        with st.spinner("Running symbol optimizer..."):
            st.session_state.optimizer_output = service.run_optimizer(
                st.session_state.history_fetch_symbol,
                st.session_state.history_fetch_timeframe,
            )

    fetch_result = st.session_state.history_fetch_result or {}
    if fetch_result:
        message = str(fetch_result.get("status_message", ""))
        if bool(fetch_result.get("success", False)):
            st.success(message)
        else:
            st.warning(message)

    payload = service.learning_center_payload()
    selected_symbol = str(st.session_state.get("selected_symbol", "EURUSD"))
    selected_timeframe = str(st.session_state.get("selected_timeframe", "M5"))
    market_status, _market_detail = service.connection_status(selected_symbol, selected_timeframe)
    diagnostics = build_learning_diagnostics(
        active=payload["active"],
        candidates=payload["candidates"],
        paper_trades=service.load_paper_trades(limit=500),
        historical_validation=payload["historical_validation"],
        state_changes=payload["state_changes_prepared"],
        events=payload["events"],
        market_status=market_status,
    )
    inventory = service.historical_data_summary()
    has_history = not inventory.empty

    st.markdown("## Learning Diagnostics Summary")
    st.caption("Operator-grade diagnostics for learning trend, confidence, and evidence quality.")
    summary = diagnostics["summary_metrics"]
    cards_a = st.columns(5, gap="small")
    cards_a[0].metric("Total Paper Trades", int(summary["total_paper_trades"]))
    cards_a[1].metric("Win Rate", f"{float(summary['win_rate']) * 100:.1f}%")
    cards_a[2].metric("Net PnL", f"{float(summary['net_pnl']):.2f}")
    cards_a[3].metric("Max Drawdown", f"{float(summary['max_drawdown']):.2f}")
    pf = summary["profit_factor"]
    cards_a[4].metric("Profit Factor", "∞" if pf == float("inf") else f"{float(pf):.2f}")

    cards_b = st.columns(6, gap="small")
    cards_b[0].metric("Open Paper Trades", int(summary["open_paper_trades"]))
    cards_b[1].metric("Closed Paper Trades", int(summary["closed_paper_trades"]))
    cards_b[2].metric("Loss Rate", f"{float(summary['loss_rate']) * 100:.1f}%")
    cards_b[3].metric("Avg PnL", f"{float(summary['average_pnl']):.3f}")
    cards_b[4].metric("Expectancy", f"{float(summary['expectancy']):.3f}")
    cards_b[5].metric("Best Active Strategy Count", int(diagnostics["strategy_state_counts"].get("active", 0)))

    cards_c = st.columns(3, gap="small")
    cards_c[0].metric("Learning Trend", diagnostics["trend_status"].replace("_", " ").upper())
    cards_c[1].metric("Learning Health", diagnostics["learning_health"].replace("_", " ").upper())
    cards_c[2].metric("System Readiness", diagnostics["readiness"]["status"].replace("_", " ").upper())
    st.caption(diagnostics["trend_reason"])
    st.caption(f"Readiness rationale: {diagnostics['readiness']['reason']}")

    st.markdown("### Market-Aware Learning Context")
    if market_status == "closed":
        st.info("Market is closed today. No new live/paper opportunities are expected; this is not treated as degradation.")
    elif market_status == "open":
        st.success("Market is open. New forward paper-trade evidence can accumulate in monitor mode.")
    else:
        st.caption(f"Market status for {selected_symbol}/{selected_timeframe}: {market_status}.")

    if int(summary["total_paper_trades"]) == 0:
        st.info(
            "No paper trades yet: historical learning can still exist, but forward learning is not established yet. "
            "Run Historical Validation + Symbol Optimizer, then wait for market open and start monitor mode."
        )

    st.markdown("### Rolling Performance Analysis")
    rolling = diagnostics["rolling_performance"]
    roll_df = pd.DataFrame(
        [
            {"window": "Last 20", **rolling["last_20"]},
            {"window": "Last 50", **rolling["last_50"]},
            {"window": "Last 100", **rolling["last_100"]},
        ]
    )
    st.dataframe(roll_df, use_container_width=True, hide_index=True, height=180)
    st.caption(f"Recent vs long-term classification: {diagnostics['trend_status']}")

    st.markdown("### Warning & Attention Panel")
    warning_cards = diagnostics["warnings"]
    if warning_cards:
        for item in warning_cards:
            msg = f"**{item['title']}** — {item['message']}"
            if item["severity"] == "critical":
                st.error(msg)
            elif item["severity"] == "warning":
                st.warning(msg)
            else:
                st.info(msg)
    else:
        st.success("No active warning conditions detected.")

    st.markdown("### Learning Evidence Quality")
    evidence = diagnostics["evidence_quality"]
    q = st.columns(5, gap="small")
    q[0].metric("Historical Evidence", str(evidence["historical_evidence_quality"]).upper())
    q[1].metric("Forward Evidence", str(evidence["forward_evidence_quality"]).upper())
    q[2].metric("Combined Evidence", str(evidence["combined_evidence_quality"]).upper())
    q[3].metric("Sample Sufficiency", str(evidence["sample_sufficiency"]).upper())
    q[4].metric("Confidence Basis", str(evidence["confidence_basis"]).replace("_", "+").upper())

    st.markdown("### Recent Learning Changes")
    changes = diagnostics["recent_learning_changes"]
    c = st.columns(6, gap="small")
    c[0].metric("Promoted", int(changes["promoted_strategies"]))
    c[1].metric("Demoted", int(changes["demoted_strategies"]))
    c[2].metric("Disabled", int(changes["disabled_strategies"]))
    c[3].metric("To Probation", int(changes["moved_to_probation"]))
    c[4].metric("Best Params Changed", int(changes["best_params_changed"]))
    c[5].metric("Optimizer Improvements", int(changes["optimizer_improvements"]))

    st.markdown("### Best Strategy per Symbol")
    best_symbol = diagnostics["best_strategy_per_symbol"]
    st.dataframe(
        best_symbol if not best_symbol.empty else pd.DataFrame([{"info": "No strategy ranking yet. Run Symbol Optimizer after historical validation."}]),
        use_container_width=True,
        hide_index=True,
        height=220,
    )

    st.markdown("### Strategy Lifecycle Visibility")
    state_counts = diagnostics["strategy_state_counts"]
    s_cols = st.columns(5, gap="small")
    for idx, key in enumerate(["active", "candidate", "probation", "disabled", "archived"]):
        s_cols[idx].metric(key.title(), int(state_counts.get(key, 0)))

    st.markdown("### Historical Learning Panels")
    row_a, row_b = st.columns(2, gap="small")
    with row_a:
        st.markdown("#### Stored Historical Datasets")
        if has_history:
            st.dataframe(inventory, use_container_width=True, hide_index=True, height=240)
        else:
            st.info("No historical datasets stored yet. Fetch historical data to initialize learning.")
    with row_b:
        st.markdown("#### Validation Summaries")
        historical = payload["historical_validation"]
        if not historical.empty:
            summary = (
                historical.groupby(["symbol", "timeframe"], dropna=False)
                .agg(
                    rows=("strategy", "count"),
                    top_strategy=("strategy", "first"),
                    best_score=("final_validation_score", "max"),
                    avg_score=("final_validation_score", "mean"),
                )
                .reset_index()
            )
            st.dataframe(summary, use_container_width=True, hide_index=True, height=240)
        else:
            st.info("No validation summaries yet. Run Historical Validation after storing history.")

    row_c, row_d = st.columns(2, gap="small")
    with row_c:
        st.markdown("#### Top Strategies")
        historical = payload["historical_validation"]
        if not historical.empty:
            top_strategies = (
                historical.groupby("strategy", dropna=False)
                .agg(
                    best_score=("final_validation_score", "max"),
                    avg_score=("final_validation_score", "mean"),
                    rows=("strategy", "count"),
                )
                .reset_index()
                .sort_values(["best_score", "avg_score"], ascending=False)
            )
            st.dataframe(top_strategies, use_container_width=True, hide_index=True, height=240)
        else:
            st.info("No strategy rankings yet. Validation results will populate this panel.")
    with row_d:
        st.markdown("#### Top Parameter Sets")
        best_config_panel = payload.get("best_config", pd.DataFrame())
        if isinstance(best_config_panel, pd.DataFrame) and not best_config_panel.empty:
            score_col = "combined_score" if "combined_score" in best_config_panel.columns else "historical_score"
            if score_col in best_config_panel.columns:
                best_config_panel = best_config_panel.sort_values(score_col, ascending=False)
            st.dataframe(best_config_panel.head(25), use_container_width=True, hide_index=True, height=240)
        else:
            st.info("No top parameter sets yet. Run optimizer/validation to save best configs.")

    st.markdown("#### Historical Score by Symbol")
    historical = payload["historical_validation"]
    if not historical.empty:
        score_by_symbol = (
            historical.groupby("symbol", dropna=False)
            .agg(
                best_validation_score=("final_validation_score", "max"),
                average_validation_score=("final_validation_score", "mean"),
                strategy_rows=("strategy", "count"),
            )
            .reset_index()
            .sort_values("best_validation_score", ascending=False)
        )
        st.dataframe(score_by_symbol, use_container_width=True, hide_index=True, height=210)
    else:
        st.info("No historical score data available by symbol yet.")

    render_learning_health(payload)
    optimizer_board = service.optimizer_leaderboard_by_symbol()
    latest_optimizer = st.session_state.optimizer_output if "optimizer_output" in st.session_state else pd.DataFrame()
    meta = payload.get("metadata", {}) if isinstance(payload.get("metadata"), dict) else {}
    last_run = str(meta.get("last_optimization_run", "n/a"))
    latest_score = 0.0
    if isinstance(latest_optimizer, pd.DataFrame) and not latest_optimizer.empty and "score" in latest_optimizer.columns:
        latest_score = float(pd.to_numeric(latest_optimizer["score"], errors="coerce").fillna(0.0).max())
    elif not optimizer_board.empty and "best_score" in optimizer_board.columns:
        latest_score = float(pd.to_numeric(optimizer_board["best_score"], errors="coerce").fillna(0.0).max())

    panels = st.columns(2, gap="small")
    with panels[0]:
        st.markdown("### Best Params per Symbol")
        by_symbol = pd.DataFrame()
        if not optimizer_board.empty:
            by_symbol = (
                optimizer_board.sort_values(["symbol", "best_score"], ascending=[True, False])
                .drop_duplicates(subset=["symbol", "strategy_name"], keep="first")
                .reset_index(drop=True)
            )
        st.dataframe(
            by_symbol if not by_symbol.empty else pd.DataFrame([{"info": "No symbol-specific optimizer params yet"}]),
            use_container_width=True,
            hide_index=True,
            height=220,
        )
    with panels[1]:
        st.markdown("### Best Params per Timeframe")
        by_timeframe = pd.DataFrame()
        if not optimizer_board.empty and "timeframe" in optimizer_board.columns:
            by_timeframe = (
                optimizer_board.sort_values(["timeframe", "best_score"], ascending=[True, False])
                .drop_duplicates(subset=["timeframe", "strategy_name"], keep="first")
                .reset_index(drop=True)
            )
        st.dataframe(
            by_timeframe if not by_timeframe.empty else pd.DataFrame([{"info": "No timeframe-specific optimizer params yet"}]),
            use_container_width=True,
            hide_index=True,
            height=220,
        )

    run_stats = st.columns(2, gap="small")
    run_stats[0].metric("Last Optimization Run", last_run)
    run_stats[1].metric("Latest Optimization Score", f"{latest_score:.2f}")

    with st.expander("Optimizer Leaderboard by Symbol", expanded=False):
        st.dataframe(
            optimizer_board if not optimizer_board.empty else pd.DataFrame([{"info": "No optimizer leaderboard data yet"}]),
            use_container_width=True,
            hide_index=True,
            height=220,
        )
    with st.expander("Best Configuration per Symbol", expanded=False):
        best_config = payload.get("best_config", pd.DataFrame())
        st.dataframe(
            best_config if isinstance(best_config, pd.DataFrame) and not best_config.empty else pd.DataFrame([{"info": "No best configuration data yet"}]),
            use_container_width=True,
            hide_index=True,
            height=220,
        )

    row_one_left, row_one_right = st.columns(2, gap="small")
    with row_one_left:
        st.markdown("### Active Strategies")
        st.dataframe(payload["active"], use_container_width=True, hide_index=True, height=250)
    with row_one_right:
        st.markdown("### Candidate Strategies")
        st.dataframe(payload["candidates"], use_container_width=True, hide_index=True, height=250)

    st.markdown("### Strategy State Tables")
    all_strategies = pd.concat([payload["active"], payload["candidates"]], ignore_index=True)
    if not all_strategies.empty:
        all_strategies["strategy_state"] = all_strategies.get("strategy_state", "").astype(str).str.lower()
    state_panels = st.columns(5, gap="small")
    for idx, state_name in enumerate(["active", "candidate", "probation", "disabled", "archived"]):
        with state_panels[idx]:
            st.markdown(f"#### {state_name.title()}")
            subset = all_strategies[all_strategies["strategy_state"] == state_name] if not all_strategies.empty else pd.DataFrame()
            st.dataframe(
                subset if not subset.empty else pd.DataFrame([{"info": f"No {state_name} strategies"}]),
                use_container_width=True,
                hide_index=True,
                height=220,
            )

    row_two_left, row_two_right = st.columns(2, gap="small")
    with row_two_left:
        st.markdown("### Historical Validation")
        historical = payload["historical_validation"]
        st.dataframe(
            historical if not historical.empty else pd.DataFrame([{"info": "No historical validation yet"}]),
            use_container_width=True,
            hide_index=True,
            height=250,
        )
        if "validation_output" in st.session_state and not st.session_state.validation_output.empty:
            st.markdown("#### Latest Validation Run")
            st.dataframe(st.session_state.validation_output, use_container_width=True, hide_index=True, height=200)
    with row_two_right:
        st.markdown("### Paper Trades")
        paper = service.load_paper_trades(limit=200)
        st.dataframe(
            paper if not paper.empty else pd.DataFrame([{"info": "No paper trades yet"}]),
            use_container_width=True,
            hide_index=True,
            height=250,
        )

    row_three_left, row_three_right = st.columns(2, gap="small")
    with row_three_left:
        st.markdown("### State Changes")
        st.dataframe(payload["state_changes_prepared"].head(120), use_container_width=True, hide_index=True, height=240)
    with row_three_right:
        st.markdown("### Learning Events")
        st.dataframe(payload["events"].head(120), use_container_width=True, hide_index=True, height=240)
        if "optimizer_output" in st.session_state and not st.session_state.optimizer_output.empty:
            st.markdown("#### Latest Optimizer Run")
            st.dataframe(st.session_state.optimizer_output, use_container_width=True, hide_index=True, height=200)


def sidebar_controls() -> None:
    symbol_value = st.session_state.selected_symbol if st.session_state.selected_symbol in COMMON_SYMBOLS else COMMON_SYMBOLS[0]
    tf_value = st.session_state.selected_timeframe if st.session_state.selected_timeframe in TIMEFRAMES else TIMEFRAMES[1]
    st.sidebar.markdown("## Terminal Controls")
    st.session_state.selected_symbol = st.sidebar.selectbox("Active Symbol", COMMON_SYMBOLS, index=COMMON_SYMBOLS.index(symbol_value))
    st.session_state.selected_timeframe = st.sidebar.selectbox("Timeframe", TIMEFRAMES, index=TIMEFRAMES.index(tf_value))
    st.session_state.compact_mode = st.sidebar.toggle("Compact mode", value=st.session_state.compact_mode)
    st.session_state.expanded_chart = st.sidebar.toggle("Expanded chart", value=st.session_state.expanded_chart)
    st.session_state.watch_mode = st.sidebar.toggle("Watch mode", value=st.session_state.watch_mode)
    st.session_state.auto_refresh = st.sidebar.toggle("Auto refresh (stable scheduler)", value=st.session_state.auto_refresh)
    st.session_state.refresh_interval = int(st.sidebar.number_input("Live refresh (seconds)", min_value=3, max_value=3600, value=int(st.session_state.refresh_interval), step=1))
    st.session_state.monitor_running = st.sidebar.toggle("Monitor running", value=st.session_state.monitor_running)
    st.session_state.run_now = st.sidebar.button("Run cycle now", type="primary", use_container_width=True)
    st.session_state.refresh_now = st.sidebar.button("Refresh market data", use_container_width=True)
    st.session_state.run_optimizer_now = st.sidebar.button("Run optimizer", use_container_width=True)
    st.session_state.run_validation_now = st.sidebar.button("Run historical validation", use_container_width=True)
    st.sidebar.markdown("### System Controls")
    st.session_state.send_test_telegram = st.sidebar.button("Send Test Telegram Message", use_container_width=True)
    st.sidebar.caption(
        f"Last Telegram test: {st.session_state.last_telegram_test_time} | "
        f"{st.session_state.last_telegram_test_result}"
    )
    if st.session_state.last_telegram_test_reason:
        st.sidebar.caption(f"Reason: {st.session_state.last_telegram_test_reason}")


def handle_refresh() -> None:
    if st.session_state.auto_refresh:
        interval_ms = min(5000, int(st.session_state.refresh_interval) * 1000)
        try:
            from streamlit_autorefresh import st_autorefresh  # type: ignore

            st_autorefresh(interval=interval_ms, key="terminal_live_refresh")
        except Exception:
            pass


def render_monitor_state() -> None:
    runtime: MonitorState = st.session_state.monitor_runtime
    cols = st.columns(5, gap="small")
    cols[0].metric("Monitor", "RUNNING" if runtime.is_running else "STOPPED")
    cols[1].metric("Last refresh", st.session_state.last_refresh_label)
    cols[2].metric("Next refresh", st.session_state.monitor_next_refresh_label)
    cols[3].metric("Last alert", st.session_state.monitor_last_alert_label)
    cols[4].metric("Cycle #", int(st.session_state.monitor_cycle_id))
    st.caption(
        "Monitor status — "
        f"market: {st.session_state.monitor_last_market_status} | "
        f"news: {st.session_state.monitor_last_news_status} | "
        f"alert: {st.session_state.latest_alert_status}"
    )


def main() -> None:
    ensure_state()
    service = get_service()
    st.markdown(THEME_CSS, unsafe_allow_html=True)
    st.markdown("## AITrader Live Trading Terminal")
    st.caption("Local-first • MT5 market data • recommendation-only • paper-trading-only")

    sidebar_controls()

    state = prepare_live_update_state(
        {
            "symbol": st.session_state.selected_symbol,
            "timeframe": st.session_state.selected_timeframe,
            "refresh_interval": st.session_state.refresh_interval,
        },
        symbol=st.session_state.selected_symbol,
        timeframe=st.session_state.selected_timeframe,
        refresh_interval=st.session_state.refresh_interval,
        watch_mode=st.session_state.watch_mode,
        auto_refresh=st.session_state.auto_refresh,
        compact_mode=st.session_state.compact_mode,
        expanded_chart=st.session_state.expanded_chart,
    )

    runtime: MonitorState = st.session_state.monitor_runtime
    runtime.interval_seconds = max(3, int(state.refresh_interval))
    now = datetime.now(tz=timezone.utc)
    if st.session_state.monitor_running:
        if not runtime.is_running:
            runtime.start(now)
        st.session_state.monitoring_state = "running" if state.watch_mode else "polling"
    else:
        runtime.stop()
        st.session_state.monitoring_state = "stopped"

    if st.session_state.run_now:
        run_cycle(service, state.symbol, state.timeframe, state.watch_mode)
        runtime.mark_cycle_complete(interval_seconds=state.refresh_interval)
        runtime.mark_alert(status=st.session_state.latest_alert_status)
    elif runtime.should_run_cycle(now):
        run_cycle(service, state.symbol, state.timeframe, state.watch_mode)
        runtime.mark_cycle_complete(interval_seconds=state.refresh_interval)
        runtime.mark_alert(status=st.session_state.latest_alert_status)

    st.session_state.monitor_next_refresh_label = to_utc_label(runtime.next_refresh_at)
    st.session_state.monitor_last_alert_label = to_utc_label(runtime.last_alert_at)

    if st.session_state.refresh_now:
        _load_chart_candles.clear()
        _load_chart_news.clear()

    rec = st.session_state.last_recommendation
    if st.session_state.run_optimizer_now:
        with st.spinner("Running optimizer..."):
            optimizer_table = service.run_optimizer(state.symbol, state.timeframe)
        st.session_state.optimizer_output = optimizer_table
    if st.session_state.run_validation_now:
        with st.spinner("Running historical validation..."):
            validation_table = service.run_historical_validation()
        st.session_state.validation_output = validation_table

    if st.session_state.send_test_telegram:
        try:
            service.refresh_settings()
            telegram_test_result = service.send_test_telegram_message()
        except Exception as exc:  # pragma: no cover - defensive streamlit behavior
            telegram_test_result = {
                "timestamp": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
                "status": "error",
                "message": f"Telegram test failed: {exc}",
                "reason": str(exc),
            }

        st.session_state.last_telegram_test_time = telegram_test_result.get("timestamp", "Never")
        st.session_state.last_telegram_test_result = telegram_test_result.get("status", "error")
        st.session_state.last_telegram_test_reason = telegram_test_result.get("reason", "")

        status = telegram_test_result.get("status", "error")
        message = telegram_test_result.get("message", "Telegram test failed")
        if status == "success":
            st.success(message)
        elif status == "warning":
            st.warning(message)
        else:
            st.error(message)

    top_tabs = st.tabs(["Trading Cockpit", "Market Visuals", "Self-Learning Center"])
    render_monitor_state()

    with top_tabs[0]:
        render_trading_cockpit(service, state, rec)

    with top_tabs[1]:
        render_market_visuals(service, state, rec)

    with top_tabs[2]:
        render_self_learning_center(service)

    handle_refresh()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # defensive fallback for UI runtime
        st.error(f"Dashboard runtime error: {exc}")
        st.code(traceback.format_exc())
