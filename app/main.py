"""CLI entrypoint for trading recommendations."""

from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import timezone
from pathlib import Path
from typing import Any

from config_loader import load_settings
from core.mt5_client import MT5Client
from learning.optimizer import ParameterOptimizer
from logs.logger import configure_logging
from news.filter import NewsFilter
from news.providers import build_news_provider
from recommendation.engine import RecommendationEngine
from strategy.registry import create_default_strategies

LOGGER = logging.getLogger(__name__)
MONITOR_LOG_PATH = Path("logs/monitor_cycles.jsonl")


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI parser."""
    parser = argparse.ArgumentParser(
        description="MT5 AI-assisted recommendation system (paper trading only)"
    )
    parser.add_argument("--symbol", required=True, help="Symbol like EURUSD")
    parser.add_argument("--timeframe", default="M5", help="M1/M5/M15/M30/H1/H4/D1")
    parser.add_argument("--settings", default="config/settings.yaml", help="Path to settings YAML")
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Continuously regenerate recommendations on an interval",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=300,
        help="Watch mode interval in seconds (default: 300)",
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
        "news_status": recommendation.news_status,
        "selected_strategy": recommendation.selected_strategy,
        "action": action,
        "entry": recommendation.entry,
        "stop_loss": recommendation.stop_loss,
        "take_profit": recommendation.take_profit,
        "confidence": recommendation.confidence,
        "risk_reward": recommendation.risk_reward,
        "reasons": recommendation.reasons,
    }


def _persist_cycle_result(
    recommendation: Any | None,
    cycle: int,
    interval_seconds: int,
    error: str | None = None,
) -> None:
    MONITOR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {
        "cycle": cycle,
        "interval_seconds": interval_seconds,
        "error": error,
    }

    if recommendation is not None:
        payload["recommendation"] = _recommendation_to_dict(recommendation)

    with MONITOR_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")


def build_engine(settings: Any) -> RecommendationEngine:
    return RecommendationEngine(
        mt5_client=MT5Client(),
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


def run(engine: RecommendationEngine, args: argparse.Namespace) -> None:
    interval = max(1, int(args.interval))
    cycle = 1

    while True:
        try:
            recommendation = engine.generate(
                symbol=args.symbol.upper(),
                timeframe=args.timeframe.upper(),
            )

            print(f"\n--- Cycle {cycle} ---")
            print(f"Market status: {recommendation.market_status}")

            is_news_blocked = recommendation.news_status == "blocked"
            print(f"Trading blocked by news: {'yes' if is_news_blocked else 'no'}")

            if recommendation.action != "NO_TRADE":
                print(engine.format_for_terminal(recommendation))
            else:
                print("No actionable recommendation this cycle.")

            if recommendation.market_status == "mt5_unavailable":
                print("MT5 appears disconnected; will retry next cycle.")

            print(json.dumps(_recommendation_to_dict(recommendation), indent=2))

            _persist_cycle_result(
                recommendation,
                cycle=cycle,
                interval_seconds=interval,
            )

        except Exception as exc:
            LOGGER.exception("Cycle %s failed while generating recommendation", cycle)
            print(json.dumps({"error": f"Cycle {cycle} failed: {exc}"}, indent=2))

            _persist_cycle_result(
                None,
                cycle=cycle,
                interval_seconds=interval,
                error=str(exc),
            )

            if not args.watch:
                break

        if not args.watch:
            break

        LOGGER.info("Sleeping %s seconds before next watch cycle", interval)
        time.sleep(interval)
        cycle += 1


def main() -> None:
    """Run the recommendation CLI and print JSON output."""
    args = build_parser().parse_args()
    settings = load_settings(args.settings)
    configure_logging(settings.get("app.log_level", "INFO"))

    engine = build_engine(settings)
    run(engine, args)


if __name__ == "__main__":
    try:
        main()
    except FileNotFoundError as exc:
        print(json.dumps({"error": str(exc)}, indent=2))
    except Exception as exc:  # safety net for CLI runtime
        LOGGER.exception("Unhandled error in recommendation CLI")
        print(json.dumps({"error": f"Unexpected runtime error: {exc}"}, indent=2))