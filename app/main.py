"""CLI entrypoint for trading recommendations."""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict

from config_loader import load_settings
from core.mt5_client import MT5Client
from learning.optimizer import ParameterOptimizer
from logs.logger import configure_logging
from news.filter import NewsFilter
from news.forexfactory_provider import ForexFactoryProvider
from recommendation.engine import RecommendationEngine
from strategy.breakout_atr import BreakoutATRStrategy
from strategy.trend_rsi import TrendRSIStrategy

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI parser."""
    parser = argparse.ArgumentParser(description="MT5 AI-assisted recommendation system (paper trading only)")
    parser.add_argument("--symbol", required=True, help="Symbol like EURUSD")
    parser.add_argument("--timeframe", default="M5", help="M1/M5/M15/M30/H1/H4/D1")
    parser.add_argument("--settings", default="config/settings.yaml", help="Path to settings YAML")
    return parser


def main() -> None:
    """Run the recommendation CLI and print JSON output."""
    args = build_parser().parse_args()

    settings = load_settings(args.settings)
    configure_logging(settings.get("app.log_level", "INFO"))

    engine = RecommendationEngine(
        mt5_client=MT5Client(),
        news_provider=ForexFactoryProvider(endpoint=settings.get("news.endpoint", "")),
        news_filter=NewsFilter(
            before_minutes=int(settings.get("news.high_impact_cooldown_before_min", 30)),
            after_minutes=int(settings.get("news.high_impact_cooldown_after_min", 30)),
        ),
        strategies=[TrendRSIStrategy(), BreakoutATRStrategy()],
        settings=settings,
        optimizer=ParameterOptimizer(
            lookahead_bars=int(settings.get("learning.lookahead_bars", 8)),
            min_history_bars=int(settings.get("learning.min_history_bars", 120)),
            step=int(settings.get("learning.backtest_step", 10)),
        ),
    )

    recommendation = engine.generate(symbol=args.symbol.upper(), timeframe=args.timeframe.upper())
    print(json.dumps(asdict(recommendation), indent=2, default=str))


if __name__ == "__main__":
    try:
        main()
    except FileNotFoundError as exc:
        print(json.dumps({"error": str(exc)}, indent=2))
    except Exception as exc:  # safety net for CLI runtime
        LOGGER.exception("Unhandled error in recommendation CLI")
        print(json.dumps({"error": f"Unexpected runtime error: {exc}"}, indent=2))
