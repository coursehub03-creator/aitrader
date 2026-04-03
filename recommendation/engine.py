"""Recommendation engine orchestration."""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from core.mt5_client import MT5Client
from core.types import FinalRecommendation, StrategyScore, StrategySignal
from learning.optimizer import ParameterOptimizer
from news.base import NewsProvider
from news.filter import NewsFilter
from news.symbols import currencies_for_symbol
from strategy.base import TradingStrategy

LOGGER = logging.getLogger(__name__)


class RecommendationEngine:
    """Coordinates data retrieval, news gating, strategy signals, and final decision."""

    def __init__(
        self,
        mt5_client: MT5Client,
        news_provider: NewsProvider,
        news_filter: NewsFilter,
        strategies: list[TradingStrategy],
        settings: Any,
        optimizer: ParameterOptimizer,
    ) -> None:
        self.mt5 = mt5_client
        self.news_provider = news_provider
        self.news_filter = news_filter
        self.strategies = strategies
        self.settings = settings
        self.optimizer = optimizer
        self.results_path = Path("logs/paper_trade_results.jsonl")
        self.results_path.parent.mkdir(parents=True, exist_ok=True)

    def generate(self, symbol: str, timeframe: str) -> FinalRecommendation:
        self.mt5.connect()
        try:
            if not self.mt5.connected:
                return self._no_trade(symbol, timeframe, self.mt5.status_message)

            if not self.mt5.ensure_symbol(symbol):
                return self._no_trade(symbol, timeframe, self.mt5.status_message)

            candles = self.mt5.get_ohlcv(
                symbol,
                timeframe,
                int(self.settings.get("app.data_bars", 500)),
            )
            if candles.empty:
                reason = self.mt5.status_message or f"No market data for {symbol}/{timeframe}"
                return self._no_trade(symbol, timeframe, reason)

            blocked, reason, confidence_multiplier = self._news_gate(symbol)
            if blocked:
                return self._no_trade(symbol, timeframe, reason)

            strategy_outputs = self._run_strategies(symbol, candles)
            if not strategy_outputs:
                return self._no_trade(symbol, timeframe, "No strategy produced an actionable signal")

            return self._aggregate(symbol, timeframe, strategy_outputs, confidence_multiplier)

        finally:
            self.mt5.shutdown()

    def _run_strategies(
        self,
        symbol: str,
        candles: pd.DataFrame,
    ) -> list[tuple[StrategySignal, StrategyScore | None]]:
        outputs: list[tuple[StrategySignal, StrategyScore | None]] = []

        grid_root = self.settings.get("learning.parameter_grid", {})
        optimization_enabled = bool(self.settings.get("learning.optimization_enabled", True))

        for strategy in self.strategies:
            defaults = dict(self.settings.get(f"strategy.{strategy.name}", {}))
            params = dict(defaults)
            score: StrategyScore | None = None

            if optimization_enabled:
                grid = dict(grid_root.get(strategy.name, {}))
                fixed = {k: v for k, v in defaults.items() if k not in grid}
                opt = self.optimizer.optimize(strategy, candles, grid, symbol, fixed)

                if opt is not None:
                    params = opt.best_params
                    score = StrategyScore(strategy.name, opt.best_score, 0.0, 0, 0.0, 0.0, 0.0)

            signal = strategy.generate_signal(candles, params)
            if signal is None:
                continue

            signal.metadata["active_params"] = params
            outputs.append((signal, score))

            self._persist_signal(symbol, signal)

        return outputs

    def _news_gate(self, symbol: str) -> tuple[bool, str, float]:
        now = self.mt5.now()
        try:
            events = self.news_provider.fetch_events(
                now - timedelta(hours=4),
                now + timedelta(hours=24),
            )
        except Exception as exc:  # defensive fallback for custom providers
            LOGGER.warning("News provider failed; continuing without news events: %s", exc)
            events = []

        symbol_currencies = currencies_for_symbol(symbol, self.settings.get("news.symbols_map", {}))
        decision = self.news_filter.evaluate(now, events, symbol_currencies)

        if decision.decision == "block trading":
            LOGGER.info("Recommendation blocked by news filter: %s", decision.reason)
            return True, decision.reason, decision.confidence_multiplier

        if decision.decision == "reduce confidence":
            LOGGER.info("Recommendation confidence reduced by news filter: %s", decision.reason)

        return False, decision.reason, decision.confidence_multiplier

    def _aggregate(
        self,
        symbol: str,
        timeframe: str,
        strategy_outputs: list[tuple[StrategySignal, StrategyScore | None]],
        confidence_multiplier: float = 1.0,
    ) -> FinalRecommendation:
        buys = [item for item in strategy_outputs if item[0].action == "Buy"]
        sells = [item for item in strategy_outputs if item[0].action == "Sell"]

        if buys and sells:
            return self._no_trade(symbol, timeframe, "Conflicting strategy directions")

        selected = buys if buys else sells

        confidence_weighted = 0.0
        weight_total = 0.0

        entry_vals: list[float] = []
        sl_vals: list[float] = []
        tp_vals: list[float] = []
        reasons: list[str] = []
        names: list[str] = []

        for signal, score in selected:
            weight = max(1.0, score.score / 10.0) if score else 1.0

            confidence_weighted += signal.confidence * weight
            weight_total += weight

            entry_vals.append(signal.entry)
            sl_vals.append(signal.stop_loss)
            tp_vals.append(signal.take_profit)

            reasons.append(f"{signal.strategy_name}: {signal.reason}")
            names.append(signal.strategy_name)

        return FinalRecommendation(
            symbol=symbol,
            timeframe=timeframe,
            action=selected[0][0].action,
            entry=float(sum(entry_vals) / len(entry_vals)),
            stop_loss=float(sum(sl_vals) / len(sl_vals)),
            take_profit=float(sum(tp_vals) / len(tp_vals)),
            confidence=float((confidence_weighted / weight_total) * confidence_multiplier),
            reason=" | ".join(reasons),
            contributing_strategies=names,
        )

    @staticmethod
    def _no_trade(symbol: str, timeframe: str, reason: str) -> FinalRecommendation:
        return FinalRecommendation(
            symbol,
            timeframe,
            "No Trade",
            0.0,
            0.0,
            0.0,
            0.0,
            reason,
            [],
        )

    def _persist_signal(self, symbol: str, signal: StrategySignal) -> None:
        with self.results_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "symbol": symbol,
                        "strategy": signal.strategy_name,
                        "action": signal.action,
                        "entry": signal.entry,
                        "stop_loss": signal.stop_loss,
                        "take_profit": signal.take_profit,
                        "confidence": signal.confidence,
                        "reason": signal.reason,
                        "metadata": signal.metadata,
                    }
                )
                + "\n"
            )
