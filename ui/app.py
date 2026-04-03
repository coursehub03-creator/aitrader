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
from ui.charting import ChartControls, build_market_figure, prepare_chart_payload
from ui.dashboard_service import DashboardService
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
        "alert_suppressed_reason": "",
        "monitoring_state": "idle",
        "watch_mode": False,
        "auto_refresh": False,
        "refresh_interval": 15,
        "compact_mode": False,
        "expanded_chart": False,
        "recommendation_history": [],
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
    recommendation = normalize_recommendation(service.generate_recommendation(symbol, timeframe))
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

    if watch_mode:
        status, reason, triggered, alert_type = service.evaluate_and_send_alert(recommendation)
        service.persist_alert_event(recommendation, status, reason, triggered, alert_type)
        st.session_state.latest_alert_status = status
        st.session_state.latest_alert_reason = reason
        st.session_state.alert_suppressed_reason = reason if status == "suppressed" else ""
    else:
        st.session_state.latest_alert_status = "not_evaluated"
        st.session_state.latest_alert_reason = "watch mode disabled"
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
    html = "".join([f"<div class='terminal-pill'><div class='terminal-k'>{k}</div><div class='terminal-v'>{v}</div></div>" for k, v in rows])
    st.markdown(f"<div class='terminal-strip'>{html}</div>", unsafe_allow_html=True)


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

    st.plotly_chart(build_market_figure(payload, controls), use_container_width=True, theme=None)


def render_recommendation_panel(recommendation: FinalRecommendation | None) -> None:
    panel = prepare_recommendation_panel(recommendation)
    cls = "rec-active" if panel["state"] == "active" else "rec-blocked"
    st.markdown(f"<div class='rec-card {cls}'><div class='small-muted'>Current Recommendation</div><h3 style='margin-top:0.2rem'>{panel['title']}</h3></div>", unsafe_allow_html=True)
    for k, v in panel["fields"]:
        st.metric(k.replace("_", " ").title(), v)
    if panel.get("rejection_reason"):
        st.warning(panel["rejection_reason"])
    if panel["reasons"]:
        with st.expander("Reasons", expanded=True):
            for reason in panel["reasons"]:
                st.markdown(f"- {reason}")


def render_bottom_panels(service: DashboardService) -> None:
    tabs = st.tabs(["History", "Paper Trades", "Alerts", "Learning Activity"])
    with tabs[0]:
        recent_disk = service.recent_recommendations(limit=80)
        recent = pd.DataFrame(st.session_state.recommendation_history)
        merged = pd.concat([recent, recent_disk], ignore_index=True).drop_duplicates(subset=["timestamp", "symbol", "selected_strategy", "action"], keep="first") if not recent.empty else recent_disk
        st.dataframe(merged.head(120), use_container_width=True, hide_index=True, height=280)
    with tabs[1]:
        paper = service.load_paper_trades(limit=120)
        st.dataframe(paper if not paper.empty else pd.DataFrame([{"info": "No paper trades yet"}]), use_container_width=True, hide_index=True, height=280)
    with tabs[2]:
        alerts = prepare_alert_rows(service.recent_alert_events(limit=80), limit=80)
        st.dataframe(alerts if not alerts.empty else pd.DataFrame([{"info": "No alerts yet"}]), use_container_width=True, hide_index=True, height=280)
        st.caption(f"Telegram status: {st.session_state.latest_alert_status} | reason: {st.session_state.latest_alert_reason or 'n/a'}")
    with tabs[3]:
        payload = service.learning_center_payload()
        health = payload["health"]
        m = st.columns(6)
        m[0].metric("Learning Health", str(health.get("status", "n/a")).upper())
        m[1].metric("Active Strategies", health.get("active_strategies", 0))
        m[2].metric("Candidates", health.get("candidate_strategies", 0))
        m[3].metric("Disabled", health.get("disabled_strategies", 0))
        m[4].metric("Last Optimization", health.get("last_optimization_run", "n/a"))
        m[5].metric("Last Validation", health.get("last_historical_validation_run", "n/a"))
        st.dataframe(payload["events"].head(80), use_container_width=True, hide_index=True, height=240)


def sidebar_controls() -> None:
    st.sidebar.markdown("## Terminal Controls")
    st.session_state.selected_symbol = st.sidebar.selectbox("Active Symbol", COMMON_SYMBOLS, index=max(0, COMMON_SYMBOLS.index(st.session_state.selected_symbol)))
    st.session_state.selected_timeframe = st.sidebar.selectbox("Timeframe", TIMEFRAMES, index=max(0, TIMEFRAMES.index(st.session_state.selected_timeframe)))
    st.session_state.compact_mode = st.sidebar.toggle("Compact mode", value=st.session_state.compact_mode)
    st.session_state.expanded_chart = st.sidebar.toggle("Expanded chart", value=st.session_state.expanded_chart)
    st.session_state.watch_mode = st.sidebar.toggle("Watch mode", value=st.session_state.watch_mode)
    st.session_state.auto_refresh = st.sidebar.toggle("Auto refresh", value=st.session_state.auto_refresh)
    st.session_state.refresh_interval = int(st.sidebar.number_input("Live refresh (seconds)", min_value=3, max_value=3600, value=int(st.session_state.refresh_interval), step=1))
    st.session_state.run_now = st.sidebar.button("Run cycle now", type="primary", use_container_width=True)


def handle_refresh() -> None:
    if st.session_state.auto_refresh:
        interval_ms = int(st.session_state.refresh_interval) * 1000
        try:
            from streamlit_autorefresh import st_autorefresh  # type: ignore

            st_autorefresh(interval=interval_ms, key="terminal_live_refresh")
        except Exception:
            st.markdown(f"<meta http-equiv='refresh' content='{st.session_state.refresh_interval}'>", unsafe_allow_html=True)


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

    if st.session_state.run_now or st.session_state.auto_refresh:
        st.session_state.monitoring_state = "running" if state.watch_mode else "polling"
        run_cycle(service, state.symbol, state.timeframe, state.watch_mode)
    else:
        st.session_state.monitoring_state = "idle"

    rec = st.session_state.last_recommendation
    _, snapshots = render_watchlist(service, COMMON_SYMBOLS, state.timeframe, st.session_state.recommendations_by_symbol)
    render_status_strip(rec, state.symbol, state.timeframe, snapshots)

    if rec and rec.market_status == "mt5_unavailable":
        st.error("⚠️ MT5 is unavailable. Dashboard remains live but recommendations are forced to NO_TRADE.")
    if rec and rec.market_status == "closed":
        st.warning("🚫 Market is closed for active symbol/timeframe.")

    left, center, right = st.columns([1.05, 2.65 if state.expanded_chart else 2.15, 1.15], gap="small")

    with left:
        st.markdown("### Watchlist")
        for sym in COMMON_SYMBOLS:
            if st.button(sym, key=f"jump_{sym}", use_container_width=True):
                st.session_state.selected_symbol = sym
                st.rerun()
        st.caption(f"Monitoring: {st.session_state.monitoring_state} • Last refresh: {st.session_state.last_refresh_label}")

    with center:
        st.markdown("### Market Workspace")
        render_chart(service, state.symbol, state.timeframe, rec, state.expanded_chart)

    with right:
        st.markdown("### Intelligence")
        render_recommendation_panel(rec)
        if rec is not None:
            st.metric("Market Status", rec.market_status)
            st.metric("News Status", rec.news_status)
            st.metric("Spread State", rec.spread_state)
            st.metric("Symbol Profile", rec.symbol_profile)

    if not state.compact_mode:
        st.markdown("---")
        render_bottom_panels(service)

    handle_refresh()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # defensive fallback for UI runtime
        st.error(f"Dashboard runtime error: {exc}")
        st.code(traceback.format_exc())
