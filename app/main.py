"""CLI entrypoint for trading recommendations."""

from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config_loader import load_settings
from core.mt5_client import MT5Client
from learning.optimizer import ParameterOptimizer
from logs.logger import configure_logging
from monitoring.alerts import AlertCooldownStore, AlertHistoryStore, AlertPolicy
from news.filter import NewsFilter
from news.providers import build_news_provider
from notification.telegram_notifier import TelegramConfig, TelegramNotifier
from recommendation.engine import RecommendationEngine
from strategy.registry import create_default_strategies

LOGGER = logging.getLogger(__name__)
MONITOR_LOG_PATH = Path("logs/monitor_cycles.jsonl")
ALERT_LOG_PATH = Path("logs/alert_history.jsonl")
ALERT_STATE_PATH = Path("logs/alert_state.json")
ALERT_SENT_HISTORY_PATH = Path("logs/alert_sent_history.jsonl")


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI parser."""
    parser = argparse.ArgumentParser(
        description="MT5 AI-assisted recommendation system (paper trading only)"
    )
    parser.add_argument("--symbol", help="Single symbol like EURUSD")
    parser.add_argument(
        "--symbols",
        help="Comma-separated symbols for monitor mode, e.g. EURUSD,GBPUSD,XAUUSD",
    )
    parser.add_argument("--timeframe", default="M5", help="M1/M5/M15/M30/H1/H4/D1")
    parser.add_argument("--settings", default="config/settings.yaml", help="Path to settings YAML")
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Continuously regenerate recommendations on an interval",
    )
    parser.add_argument(
        "--monitor",
        action="store_true",
        help="Alias for --watch monitor mode",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=300,
        help="Watch/monitor mode interval in seconds (default: 300)",
    )
    parser.add_argument(
        "--cooldown",
        type=int,
        default=None,
        help="Optional alert cooldown in seconds (overrides settings)",
    )
    return parser


def _recommendation_to_dict(recommendation: Any) -> dict[str, Any]:
    action = (
        recommendation.action.value
        if hasattr(recommendation.action, "value")
        else recommendation.action
    )

    return {
        "symbol": recommendation.symbol,
        "timeframe": recommendation.timeframe,
        "timestamp": recommendation.timestamp.replace(tzinfo=timezone.utc).isoformat(),
        "market_status": recommendation.market_status,
        "mt5_connection_status": getattr(recommendation, "mt5_connection_status", "unknown"),
        "news_status": recommendation.news_status,
        "symbol_profile": getattr(recommendation, "symbol_profile", "default"),
        "session_state": getattr(recommendation, "session_state", "unknown"),
        "spread_state": getattr(recommendation, "spread_state", "unknown"),
        "spread_value": getattr(recommendation, "spread_value", 0.0),
        "selected_strategy": recommendation.selected_strategy,
        "action": action,
        "entry": recommendation.entry,
        "stop_loss": recommendation.stop_loss,
        "take_profit": recommendation.take_profit,
        "confidence": recommendation.confidence,
        "risk_reward": recommendation.risk_reward,
        "signal_strength": getattr(recommendation, "signal_strength", "weak"),
        "rejection_reason": getattr(recommendation, "rejection_reason", None),
        "volatility_state": getattr(recommendation, "volatility_state", "normal"),
        "next_relevant_news_event": getattr(recommendation, "next_relevant_news_event", None),
        "next_relevant_news_countdown": getattr(recommendation, "next_relevant_news_countdown", None),
        "reasons": recommendation.reasons,
    }


def _persist_cycle_result(
    recommendation: Any | None,
    cycle: int,
    interval_seconds: int,
    symbol: str,
    alert_status: str = "not_evaluated",
    alert_reason: str = "",
    error: str | None = None,
) -> None:
    MONITOR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {
        "cycle": cycle,
        "symbol": symbol,
        "interval_seconds": interval_seconds,
        "alert_status": alert_status,
        "alert_reason": alert_reason,
        "error": error,
    }

    if recommendation is not None:
        payload["recommendation"] = _recommendation_to_dict(recommendation)

    with MONITOR_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")


def _persist_alert_result(
    recommendation: Any,
    cycle: int,
    symbol: str,
    sent: bool,
    status: str,
    reason: str,
    alert_type: str,
) -> None:
    ALERT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "cycle": cycle,
        "symbol": symbol,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        "timeframe": recommendation.timeframe,
        "alert_type": alert_type,
        "message_summary": f"{symbol} {recommendation.timeframe} {recommendation.action} {recommendation.signal_strength}",
        "sent": sent,
        "status": status,
        "suppression_reason": reason if status == "suppressed" else "",
        "reason": reason,
        "recommendation": _recommendation_to_dict(recommendation),
    }
    with ALERT_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")


def _resolve_symbols(args: argparse.Namespace, settings: Any) -> list[str]:
    if args.symbols:
        selected = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
        if selected:
            return selected
    if args.symbol:
        return [args.symbol.upper()]
    configured = settings.get("monitoring.symbols", [])
    if isinstance(configured, list) and configured:
        return [str(item).upper() for item in configured]
    return ["EURUSD"]


def build_engine(settings: Any) -> RecommendationEngine:
    mt5_client = MT5Client(
        terminal_path=settings.get("mt5.terminal_path"),
        login=settings.get("mt5.login"),
        password=settings.get("mt5.password"),
        server=settings.get("mt5.server"),
        init_retries=int(settings.get("mt5.init_retries", 3)),
        retry_delay_seconds=float(settings.get("mt5.retry_delay_seconds", 0.5)),
    )
    return RecommendationEngine(
        mt5_client=mt5_client,
        news_provider=build_news_provider(settings),
        news_filter=NewsFilter(
            before_minutes=int(settings.get("news.high_impact_cooldown_before_min", 30)),
            after_minutes=int(settings.get("news.high_impact_cooldown_after_min", 15)),
            medium_impact_confidence_multiplier=float(
                settings.get("news.medium_impact_confidence_multiplier", 0.7)
            ),
        ),
        strategies=create_default_strategies(),
        settings=settings,
        optimizer=ParameterOptimizer(
            lookahead_bars=int(settings.get("learning.lookahead_bars", 8)),
            min_history_bars=int(settings.get("learning.min_history_bars", 120)),
            step=int(settings.get("learning.backtest_step", 10)),
            search_method=str(settings.get("learning.search_method", "grid")),
            random_search_trials=int(settings.get("learning.random_search_trials", 20)),
            min_validation_trades=int(settings.get("learning.min_validation_trades", 2)),
            min_forward_trades=int(settings.get("learning.min_forward_trades", 2)),
            report_dir=str(
                settings.get("learning.optimization_report_dir", "logs/optimization")
            ),
        ),
    )


def _build_telegram_notifier(settings: Any) -> TelegramNotifier:
    return TelegramNotifier.from_settings(settings)


def run(engine: RecommendationEngine, args: argparse.Namespace, settings: Any | None = None) -> None:
    interval = max(1, int(args.interval))
    settings = settings or {}
    watch_mode = bool(args.watch or getattr(args, "monitor", False))
    symbols = _resolve_symbols(args, settings)
    cycle = 1

    min_confidence = (
        float(settings.get("monitoring.minimum_confidence_for_alert", settings.get("recommendation.min_confidence", 0.6)))
        if hasattr(settings, "get")
        else 0.6
    )
    min_rr = float(settings.get("recommendation.min_risk_reward", 1.5)) if hasattr(settings, "get") else 1.5
    policy = AlertPolicy(
        min_confidence=min_confidence,
        min_risk_reward=min_rr,
        min_signal_strength=str(
            settings.get("monitoring.minimum_signal_strength_for_alert", "strong")
        ) if hasattr(settings, "get") else "strong",
    )

    configured_cooldown = int(settings.get("monitoring.alert_cooldown_seconds", 900)) if hasattr(settings, "get") else 900
    cooldown_seconds = int(args.cooldown) if args.cooldown is not None else configured_cooldown
    cooldown_store = AlertCooldownStore(ALERT_STATE_PATH, cooldown_seconds=cooldown_seconds)
    history_store = AlertHistoryStore(
        ALERT_SENT_HISTORY_PATH,
        duplicate_window_seconds=int(settings.get("monitoring.alert_duplicate_window_seconds", 1800)) if hasattr(settings, "get") else 1800,
    )
    notifier = _build_telegram_notifier(settings) if hasattr(settings, "get") else TelegramNotifier(TelegramConfig())

    while True:
        for symbol in symbols:
            try:
                recommendation = engine.generate(
                    symbol=symbol,
                    timeframe=args.timeframe.upper(),
                )

                print(f"\n--- Cycle {cycle} ({symbol}) ---")
                print(f"Market status: {recommendation.market_status}")

                is_news_blocked = recommendation.news_status == "blocked"
                print(f"Trading blocked by news: {'yes' if is_news_blocked else 'no'}")

                if recommendation.action != "NO_TRADE":
                    print(engine.format_for_terminal(recommendation))
                else:
                    print("No actionable recommendation this cycle.")

                should_alert, qualifier_reason = policy.qualifies(recommendation)
                alert_status = "suppressed"
                alert_reason = qualifier_reason
                sent = False
                alert_type = "strong_trade_alert"

                if should_alert:
                    key = cooldown_store.build_key(recommendation)
                    now = datetime.now(tz=timezone.utc)
                    can_send, cooldown_reason = cooldown_store.can_send(key, now)
                    if can_send:
                        history_ok, history_reason, _ = history_store.suppress_duplicate(recommendation, now)
                        if history_ok:
                            sent, send_reason = notifier.send_recommendation_alert(recommendation, alert_type=alert_type)
                            alert_status = "sent" if sent else "failed"
                            alert_reason = send_reason
                            if sent:
                                cooldown_store.mark_sent(key, now)
                                history_store.mark_sent(recommendation, now)
                        else:
                            alert_status = "suppressed"
                            alert_reason = history_reason
                    else:
                        alert_status = "suppressed"
                        alert_reason = cooldown_reason
                        LOGGER.info("Alert suppressed by cooldown for %s: %s", symbol, cooldown_reason)
                elif notifier.config.send_rejected_alerts:
                    rejection_map = {
                        "market_closed_or_unavailable": "trade_blocked_by_market_closed",
                        "news_blocked": "trade_blocked_by_news",
                        "confidence_below_threshold": "trade_blocked_by_filters",
                        "risk_reward_below_threshold": "trade_blocked_by_filters",
                        "weak_or_medium_signal": "trade_blocked_by_filters",
                    }
                    mapped = rejection_map.get(qualifier_reason)
                    if mapped:
                        alert_type = "rejected_signal_alert"
                        sent, send_reason = notifier.send_recommendation_alert(recommendation, alert_type=mapped)
                        alert_status = "sent" if sent else "failed"
                        alert_reason = send_reason if sent else qualifier_reason

                if recommendation.market_status == "mt5_unavailable":
                    print("MT5 appears disconnected; will retry next cycle.")

                print(f"Alert status: {alert_status} ({alert_reason})")
                print(json.dumps(_recommendation_to_dict(recommendation), indent=2))

                _persist_cycle_result(
                    recommendation,
                    cycle=cycle,
                    interval_seconds=interval,
                    symbol=symbol,
                    alert_status=alert_status,
                    alert_reason=alert_reason,
                )
                _persist_alert_result(
                    recommendation,
                    cycle=cycle,
                    symbol=symbol,
                    sent=sent,
                    status=alert_status,
                    reason=alert_reason,
                    alert_type=alert_type,
                )

            except Exception as exc:
                LOGGER.exception("Cycle %s failed while generating recommendation for %s", cycle, symbol)
                print(json.dumps({"error": f"Cycle {cycle} failed for {symbol}: {exc}"}, indent=2))

                _persist_cycle_result(
                    None,
                    cycle=cycle,
                    interval_seconds=interval,
                    symbol=symbol,
                    error=str(exc),
                )

                if not watch_mode:
                    break

        if not watch_mode:
            break

        LOGGER.info("Sleeping %s seconds before next monitor cycle", interval)
        time.sleep(interval)
        cycle += 1


def main() -> None:
    """Run the recommendation CLI and print JSON output."""
    args = build_parser().parse_args()
    settings = load_settings(args.settings)
    configure_logging(settings.get("app.log_level", "INFO"))

    engine = build_engine(settings)
    run(engine, args, settings=settings)


if __name__ == "__main__":
    try:
        main()
    except FileNotFoundError as exc:
        print(json.dumps({"error": str(exc)}, indent=2))
    except Exception as exc:  # safety net for CLI runtime
        LOGGER.exception("Unhandled error in recommendation CLI")
        print(json.dumps({"error": f"Unexpected runtime error: {exc}"}, indent=2))
