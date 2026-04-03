"""Premium Streamlit operator dashboard for local recommendation workflows."""

from __future__ import annotations

from datetime import datetime, timezone
import traceback

import pandas as pd
import streamlit as st

from core.types import FinalRecommendation, SignalAction
from ui.dashboard_service import DashboardService


st.set_page_config(page_title="AITrader Operator Dashboard", page_icon="📈", layout="wide")

THEME_CSS = """
<style>
    .main { background: linear-gradient(180deg, #0b1220 0%, #111827 100%); }
    .block-container { padding-top: 1.2rem; padding-bottom: 2rem; }
    .dashboard-title { font-size: 2rem; font-weight: 700; color: #f8fafc; margin-bottom: 0; }
    .dashboard-subtitle { color: #cbd5e1; margin-top: 0.1rem; margin-bottom: 1rem; }
    .status-card { background: #111827; border: 1px solid #253047; border-radius: 14px; padding: 0.9rem 1rem; }
    .status-label { color: #9ca3af; font-size: 0.82rem; text-transform: uppercase; letter-spacing: .06em; }
    .status-value { color: #f8fafc; font-size: 1.25rem; font-weight: 700; }
    .accent-buy { background: linear-gradient(90deg, #14532d, #166534); border-left: 6px solid #22c55e; }
    .accent-sell { background: linear-gradient(90deg, #7f1d1d, #991b1b); border-left: 6px solid #ef4444; }
    .accent-no-trade { background: linear-gradient(90deg, #374151, #4b5563); border-left: 6px solid #9ca3af; }
    .accent-warning { background: linear-gradient(90deg, #78350f, #92400e); border-left: 6px solid #f59e0b; }
    .reason-box { background: #0f172a; border: 1px solid #334155; border-radius: 10px; padding: 0.7rem; margin-bottom: 0.4rem; color: #e5e7eb; }
</style>
"""

COMMON_SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "AUDUSD", "USDCAD"]
TIMEFRAMES = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]


@st.cache_resource
def get_service() -> DashboardService:
    return DashboardService()


def ensure_state() -> None:
    defaults = {
        "last_recommendation": None,
        "last_refresh": None,
        "debug_logs": [],
        "market_snapshot": pd.DataFrame(),
        "optimizer_table": pd.DataFrame(),
        "simulated_trades": pd.DataFrame(),
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def log_debug(message: str) -> None:
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    st.session_state.debug_logs = [f"[{timestamp}] {message}", *st.session_state.debug_logs[:99]]


def action_theme(recommendation: FinalRecommendation) -> tuple[str, str]:
    action = recommendation.action.value if hasattr(recommendation.action, "value") else str(recommendation.action)
    if recommendation.market_status != "open" or action == SignalAction.NO_TRADE:
        return "NO_TRADE", "accent-no-trade"
    if action == SignalAction.BUY:
        return "BUY", "accent-buy"
    if action == SignalAction.SELL:
        return "SELL", "accent-sell"
    return "NO_TRADE", "accent-no-trade"


def normalize_recommendation(recommendation: FinalRecommendation) -> FinalRecommendation:
    if recommendation.market_status == "closed":
        recommendation.action = SignalAction.NO_TRADE
        recommendation.reasons = recommendation.reasons + ["Market Closed: Trading recommendation suppressed by policy."]
    if recommendation.news_status == "blocked":
        recommendation.action = SignalAction.NO_TRADE
    return recommendation


def render_header(connection_status: str, last_refresh: str) -> None:
    st.markdown(THEME_CSS, unsafe_allow_html=True)
    col_left, col_right = st.columns([3, 2])
    with col_left:
        st.markdown('<p class="dashboard-title">AITrader Operator Dashboard</p>', unsafe_allow_html=True)
        st.markdown(
            '<p class="dashboard-subtitle">Premium local-first decision cockpit for MT5 recommendation workflows.</p>',
            unsafe_allow_html=True,
        )
    with col_right:
        st.markdown(
            f"""
            <div class="status-card">
              <div class="status-label">Connection Status</div>
              <div class="status-value">{connection_status}</div>
              <div class="status-label" style="margin-top:0.5rem;">Last Refresh</div>
              <div class="status-value" style="font-size:1rem;">{last_refresh}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_status_cards(recommendation: FinalRecommendation) -> None:
    cards = st.columns(5)
    cards[0].metric("Symbol", recommendation.symbol)
    cards[1].metric("Timeframe", recommendation.timeframe)
    cards[2].metric("Market Status", recommendation.market_status)
    cards[3].metric("News Status", recommendation.news_status)
    cards[4].metric("Selected Strategy", recommendation.selected_strategy)


def render_recommendation_summary(recommendation: FinalRecommendation) -> None:
    action_text, theme = action_theme(recommendation)
    st.markdown("### Recommendation Summary")

    if recommendation.market_status == "closed":
        st.error("🚫 Market Closed — no trade recommendation is allowed for this cycle.")
    elif recommendation.market_status == "mt5_unavailable":
        st.error("⚠️ MT5 unavailable — please open MetaTrader 5 and retry.")
    elif recommendation.market_status == "unavailable":
        st.warning("⚠️ Selected symbol is unavailable in MT5 Market Watch.")

    if recommendation.news_status == "blocked":
        st.error("📰 High-impact news blocked trading for this cycle.")
    elif recommendation.news_status == "reduced_confidence":
        st.warning("📰 News impact reduced confidence — review risk carefully.")

    st.markdown(
        f"""
        <div class="status-card {theme}" style="margin-bottom:0.8rem;">
          <div class="status-label">Final Decision</div>
          <div class="status-value" style="font-size:1.6rem;">{action_text}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Entry", f"{recommendation.entry:.5f}")
    c2.metric("Stop Loss", f"{recommendation.stop_loss:.5f}")
    c3.metric("Take Profit", f"{recommendation.take_profit:.5f}")
    c4.metric("Confidence", f"{recommendation.confidence:.2%}")
    st.metric("Risk / Reward", f"{recommendation.risk_reward:.2f}")


def render_market_news_panel(recommendation: FinalRecommendation) -> None:
    st.markdown("### Market and News Status")
    with st.container(border=True):
        st.write(f"**Market Status:** `{recommendation.market_status}`")
        st.write(f"**News Status:** `{recommendation.news_status}`")
        if recommendation.reasons:
            for reason in recommendation.reasons:
                st.markdown(f'<div class="reason-box">{reason}</div>', unsafe_allow_html=True)


def render_strategy_diagnostics(recommendation: FinalRecommendation) -> None:
    st.markdown("### Strategy Diagnostics")
    strategy_names = [name.strip() for name in recommendation.selected_strategy.split("+") if name.strip()]
    with st.container(border=True):
        st.write(f"**Primary Strategy:** {strategy_names[0] if strategy_names else 'none'}")
        st.write(f"**Contributing Strategies:** {', '.join(strategy_names) if strategy_names else 'n/a'}")
        st.write("**Reasons:**")
        for reason in recommendation.reasons:
            st.markdown(f"- {reason}")


def render_recent_recommendations(service: DashboardService) -> None:
    st.markdown("### Recent Recommendations")
    recent = service.recent_recommendations(limit=50)
    if recent.empty:
        st.info("No recent recommendations saved yet.")
        return
    st.dataframe(recent, use_container_width=True, hide_index=True)


def render_paper_trading_panel(service: DashboardService) -> None:
    st.markdown("### Paper Trading Panel")
    trades = service.load_paper_trades(limit=50)
    if trades.empty:
        st.info("No paper trades found yet. Run 'Simulate Paper Trade Cycle' from the sidebar.")
        return

    pnl_total = float(trades["pnl"].astype(float).sum())
    wins = int((trades["outcome"] == "WIN").sum())
    losses = int((trades["outcome"] == "LOSS").sum())

    m1, m2, m3 = st.columns(3)
    m1.metric("Total PnL", f"{pnl_total:.5f}")
    m2.metric("Wins", wins)
    m3.metric("Losses", losses)

    st.dataframe(trades, use_container_width=True, hide_index=True)


def render_leaderboard(service: DashboardService) -> None:
    st.markdown("### Leaderboard / Best Strategies")
    board = service.strategy_leaderboard(min_trades=1)
    if board.empty:
        st.info("Leaderboard is empty. Generate paper trades to score strategies.")
        return
    st.dataframe(board, use_container_width=True, hide_index=True)


def render_debug_panel() -> None:
    with st.expander("Logs / Debug Panel", expanded=False):
        if not st.session_state.debug_logs:
            st.write("No debug logs yet.")
            return
        for line in st.session_state.debug_logs:
            st.code(line)


def sidebar_controls(service: DashboardService) -> tuple[str, str, bool, int, bool]:
    st.sidebar.header("Controls")

    symbol = st.sidebar.selectbox("Symbol", COMMON_SYMBOLS, index=0)
    timeframe = st.sidebar.selectbox("Timeframe", TIMEFRAMES, index=1)

    quick = st.sidebar.columns(2)
    if quick[0].button("EURUSD"):
        symbol = "EURUSD"
    if quick[1].button("XAUUSD"):
        symbol = "XAUUSD"

    get_recommendation = st.sidebar.button("Get Recommendation", type="primary", use_container_width=True)
    auto_refresh = st.sidebar.toggle("Auto Refresh", value=False)
    interval = int(st.sidebar.number_input("Refresh interval (seconds)", min_value=5, max_value=3600, value=300, step=5))

    if st.sidebar.button("Run Optimizer", use_container_width=True):
        table = service.run_optimizer(symbol, timeframe)
        st.session_state.optimizer_table = table
        log_debug(f"Optimizer executed for {symbol}/{timeframe} ({len(table)} rows).")

    if st.sidebar.button("Refresh Market Data", use_container_width=True):
        snapshot, message = service.refresh_market_data(symbol, timeframe)
        st.session_state.market_snapshot = snapshot.tail(100)
        log_debug(f"Refresh market data: {message}")
        if snapshot.empty:
            st.sidebar.warning(message)
        else:
            st.sidebar.success(message)

    if st.sidebar.button("Simulate Paper Trade Cycle", use_container_width=True):
        simulated, message = service.simulate_paper_trade_cycle(symbol, timeframe)
        st.session_state.simulated_trades = simulated
        if simulated.empty:
            st.sidebar.warning(message)
        else:
            st.sidebar.success(message)
        log_debug(f"Paper trade simulation: {message}")

    with st.sidebar.expander("Advanced Settings", expanded=False):
        st.write("Settings file:", service.settings_path)
        if st.button("Reload Settings", use_container_width=True):
            service.refresh_settings()
            st.success("Settings reloaded")
            log_debug("Settings reloaded")

    return symbol, timeframe, get_recommendation, interval, auto_refresh


def main() -> None:
    ensure_state()
    service = get_service()

    symbol, timeframe, do_run, interval, auto_refresh = sidebar_controls(service)

    status, reason = service.connection_status(symbol, timeframe)
    connection_text = f"{status} ({reason})" if reason else status
    last_refresh = st.session_state.last_refresh or "Never"
    render_header(connection_text, last_refresh)

    if do_run or st.session_state.last_recommendation is None:
        recommendation = service.generate_recommendation(symbol, timeframe)
        recommendation = normalize_recommendation(recommendation)
        st.session_state.last_recommendation = recommendation
        st.session_state.last_refresh = datetime.now(timezone.utc).isoformat(timespec="seconds")
        log_debug(f"Recommendation generated for {symbol}/{timeframe}: action={recommendation.action}")

    rec: FinalRecommendation = st.session_state.last_recommendation
    render_status_cards(rec)

    overview_tab, history_tab, strategies_tab, logs_tab = st.tabs(["Overview", "History", "Strategies", "Logs"])

    with overview_tab:
        render_recommendation_summary(rec)
        left, right = st.columns(2)
        with left:
            render_market_news_panel(rec)
        with right:
            render_strategy_diagnostics(rec)

    with history_tab:
        render_recent_recommendations(service)
        if not st.session_state.market_snapshot.empty:
            st.markdown("### Latest Market Data Snapshot")
            st.dataframe(st.session_state.market_snapshot, use_container_width=True, hide_index=True)
        render_paper_trading_panel(service)
        if not st.session_state.simulated_trades.empty:
            st.markdown("### Last Simulation Result")
            st.dataframe(st.session_state.simulated_trades, use_container_width=True, hide_index=True)

    with strategies_tab:
        if not st.session_state.optimizer_table.empty:
            st.markdown("### Latest Optimizer Run")
            st.dataframe(st.session_state.optimizer_table, use_container_width=True, hide_index=True)
        render_leaderboard(service)

    with logs_tab:
        render_debug_panel()

    if auto_refresh:
        st.caption(f"Auto refresh enabled. Next refresh in {interval} seconds.")
        st.markdown(f"<meta http-equiv='refresh' content='{interval}'>", unsafe_allow_html=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # defensive fallback for UI runtime
        st.error(f"Dashboard runtime error: {exc}")
        st.code(traceback.format_exc())
