"""Recommendation engine orchestration."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from core.mt5_client import MT5Client
from core.types import FinalRecommendation, SignalAction, StrategyScore, StrategySignal
from learning.optimizer import OptimizationResult, ParameterOptimizer
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
        run_timestamp = datetime.utcnow()
        market_price = 0.0
        market_status = "unavailable"
        self.mt5.connect()
        try:
            if not self.mt5.connected:
                return self._no_trade(
                    symbol,
                    timeframe,
                    self.mt5.status_message,
                    "blocked",
                    "mt5_unavailable",
                    run_timestamp,
                    market_price,
                )

            market_status, market_reason = self.mt5.detect_market_status(symbol, timeframe)
            if market_status == "mt5_unavailable":
                return self._no_trade(
                    symbol,
                    timeframe,
                    market_reason,
                    "blocked",
                    market_status,
                    run_timestamp,
                    market_price,
                )
            if market_status == "unavailable":
                return self._no_trade(
                    symbol,
                    timeframe,
                    market_reason,
                    "blocked",
                    market_status,
                    run_timestamp,
                    market_price,
                )
            if market_status == "closed":
                return self._no_trade(
                    symbol,
                    timeframe,
                    f"Market is closed for {symbol}: {market_reason}",
                    "clear",
                    market_status,
                    run_timestamp,
                    market_price,
                )

            candles = self.mt5.get_ohlcv(
                symbol,
                timeframe,
                int(self.settings.get("app.data_bars", 500)),
            )
            if candles.empty:
                reason = self.mt5.status_message or f"No market data for {symbol}/{timeframe}"
                return self._no_trade(symbol, timeframe, reason, "blocked", market_status, run_timestamp, market_price)
            market_price = float(candles.iloc[-1]["close"])

            blocked, news_status, reason, confidence_multiplier = self._news_gate(symbol)
            if blocked:
                return self._no_trade(symbol, timeframe, reason, news_status, market_status, run_timestamp, market_price)

            strategy_outputs = self._run_strategies(symbol, candles)
            if not strategy_outputs:
                return self._no_trade(
                    symbol,
                    timeframe,
                    "No strategy produced an actionable signal",
                    news_status,
                    market_status,
                    run_timestamp,
                    market_price,
                )

            recommendation = self._aggregate(
                symbol,
                timeframe,
                strategy_outputs,
                market_price,
                confidence_multiplier,
                news_status,
                reason,
                market_status,
                run_timestamp,
            )
            LOGGER.info("Final recommendation generated\n%s", self.format_for_terminal(recommendation))
            return recommendation

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
        active_count = max(2, min(3, int(self.settings.get("learning.active_strategy_count", 2))))

        optimization_results = self._optimize_strategies(symbol, candles, grid_root, optimization_enabled)
        active_names = self._active_strategy_names(optimization_results, active_count, optimization_enabled)

        for strategy in self.strategies:
            if strategy.name not in active_names:
                continue

            defaults = dict(self.settings.get(f"strategy.{strategy.name}", {}))
            params = dict(defaults)
            score: StrategyScore | None = None

            opt = optimization_results.get(strategy.name)
            if opt is not None:
                params = opt.best_params
                score = StrategyScore(strategy.name, opt.best_score, 0.0, 0, 0.0, 0.0, 0.0, 0.0, 0.0)

            signal = strategy.generate_signal(candles, params)
            if signal.action == SignalAction.NO_TRADE:
                continue

            signal.metadata["active_params"] = params
            if opt is not None:
                signal.metadata["optimization_report"] = opt.report_path
            outputs.append((signal, score))

            self._persist_signal(symbol, signal)

        return outputs

    def _optimize_strategies(
        self,
        symbol: str,
        candles: pd.DataFrame,
        grid_root: dict[str, dict[str, list[Any]]],
        optimization_enabled: bool,
    ) -> dict[str, OptimizationResult]:
        if not optimization_enabled:
            return {}

        results: dict[str, OptimizationResult] = {}
        for strategy in self.strategies:
            defaults = dict(self.settings.get(f"strategy.{strategy.name}", {}))
            grid = dict(grid_root.get(strategy.name, {}))
            fixed = {k: v for k, v in defaults.items() if k not in grid}

            opt = self.optimizer.optimize(strategy, candles, grid, symbol, fixed)
            if opt is not None:
                results[strategy.name] = opt
        return results

    def _active_strategy_names(
        self,
        optimization_results: dict[str, OptimizationResult],
        active_count: int,
        optimization_enabled: bool,
    ) -> set[str]:
        if optimization_enabled and optimization_results:
            ranked = sorted(
                optimization_results.values(),
                key=lambda item: item.best_score,
                reverse=True,
            )
            return {item.strategy_name for item in ranked[:active_count]}

        return {strategy.name for strategy in self.strategies}

    def _news_gate(self, symbol: str) -> tuple[bool, str, str, float]:
        now = self.mt5.now()
        try:
            events = self.news_provider.fetch_events(
                now - timedelta(hours=4),
                now + timedelta(hours=24),
            )
        except Exception as exc:  # defensive fallback for custom providers
            LOGGER.warning("News provider failed; marking news status unknown: %s", exc)
            return False, "unknown", "News provider unavailable; decision generated without news confirmation", 1.0

        symbol_currencies = currencies_for_symbol(symbol, self.settings.get("news.symbols_map", {}))
        decision = self.news_filter.evaluate(now, events, symbol_currencies)

        if decision.decision == "block trading":
            LOGGER.info("Recommendation blocked by news filter: %s", decision.reason)
            return True, "blocked", decision.reason, decision.confidence_multiplier

        if decision.decision == "reduce confidence":
            LOGGER.info("Recommendation confidence reduced by news filter: %s", decision.reason)
            return False, "reduced_confidence", decision.reason, decision.confidence_multiplier

        return False, "clear", decision.reason, decision.confidence_multiplier

    def _aggregate(
        self,
        symbol: str,
        timeframe: str,
        strategy_outputs: list[tuple[StrategySignal, StrategyScore | None]],
        market_price: float,
        confidence_multiplier: float = 1.0,
        news_status: str = "clear",
        news_reason: str = "No relevant blocking events",
        market_status: str = "open",
        timestamp: datetime | None = None,
    ) -> FinalRecommendation:
        buys = [item for item in strategy_outputs if item[0].action == SignalAction.BUY]
        sells = [item for item in strategy_outputs if item[0].action == SignalAction.SELL]

        if buys and sells:
            return self._no_trade(
                symbol,
                timeframe,
                "Conflicting strategy directions",
                news_status,
                market_status,
                timestamp or datetime.utcnow(),
                market_price,
            )

        selected = buys if buys else sells

        confidence_weighted = 0.0
        weight_total = 0.0

        entry_vals: list[float] = []
        sl_vals: list[float] = []
        tp_vals: list[float] = []
        reasons: list[str] = [f"News status: {news_status}", f"News effect: {news_reason}"]
        names: list[str] = []
        excluded_names: list[str] = []
        weak_cutoff = float(self.settings.get("learning.weak_strategy_score_cutoff", 1.0))
        weak_reduction = float(self.settings.get("learning.weak_strategy_confidence_multiplier", 0.75))
        if weak_reduction < 0:
            weak_reduction = 0.0

        for signal, score in selected:
            perf_weight = 1.0
            if score is not None and score.score < weak_cutoff:
                if score.score <= 0:
                    excluded_names.append(signal.strategy_name)
                    reasons.append(
                        f"{signal.strategy_name} excluded due to weak recent performance score={score.score:.2f}"
                    )
                    continue
                perf_weight = weak_reduction
                reasons.append(
                    f"{signal.strategy_name} confidence reduced due to weak recent performance score={score.score:.2f}"
                )

            weight = max(1.0, score.score / 10.0) if score else 1.0

            confidence_weighted += signal.confidence * perf_weight * weight
            weight_total += weight

            entry_vals.append(signal.entry)
            sl_vals.append(signal.stop_loss)
            tp_vals.append(signal.take_profit)

            reasons.append(f"{signal.strategy_name}: {signal.reason}")
            names.append(signal.strategy_name)

        if not names:
            reason = (
                "All strategies excluded due to weak recent performance"
                if excluded_names
                else "No strategies available after aggregation"
            )
            return self._no_trade(
                symbol,
                timeframe,
                reason,
                news_status,
                market_status,
                timestamp or datetime.utcnow(),
                market_price,
            )

        avg_entry = float(sum(entry_vals) / len(entry_vals))
        avg_sl = float(sum(sl_vals) / len(sl_vals))
        avg_tp = float(sum(tp_vals) / len(tp_vals))
        risk = abs(avg_entry - avg_sl)
        reward = abs(avg_tp - avg_entry)
        risk_reward_ratio = float(reward / risk) if risk > 0 else 0.0

        return FinalRecommendation(
            symbol=symbol,
            timeframe=timeframe,
            final_action=selected[0][0].action,
            market_price=market_price,
            entry=avg_entry,
            stop_loss=avg_sl,
            take_profit=avg_tp,
            risk_reward_ratio=risk_reward_ratio,
            confidence=float((confidence_weighted / weight_total) * confidence_multiplier),
            strategy_name=names[0] if len(names) == 1 else "+".join(names),
            selected_strategy_name=names[0] if len(names) == 1 else "+".join(names),
            market_status=market_status,
            news_status=news_status,
            reasons=reasons,
            timestamp=timestamp or datetime.utcnow(),
        )

    @staticmethod
    def _no_trade(
        symbol: str,
        timeframe: str,
        reason: str,
        news_status: str,
        market_status: str,
        timestamp: datetime,
        market_price: float,
    ) -> FinalRecommendation:
        return FinalRecommendation(
            symbol=symbol,
            timeframe=timeframe,
            final_action=SignalAction.NO_TRADE,
            market_price=market_price,
            entry=0.0,
            stop_loss=0.0,
            take_profit=0.0,
            risk_reward_ratio=0.0,
            confidence=0.0,
            strategy_name="none",
            selected_strategy_name="none",
            market_status=market_status,
            news_status=news_status,
            reasons=[reason],
            timestamp=timestamp,
        )

    @staticmethod
    def format_for_terminal(recommendation: FinalRecommendation) -> str:
        news_effect = next(
            (
                reason.replace("News effect: ", "", 1)
                for reason in recommendation.reasons
                if reason.startswith("News effect: ")
            ),
            "n/a",
        )
        lines = [
            "╔══════════════════════════ FINAL RECOMMENDATION ══════════════════════════╗",
            f"║ Symbol/TF         : {recommendation.symbol}/{recommendation.timeframe}",
            f"║ Market Status     : {recommendation.market_status}",
            f"║ Action            : {recommendation.final_action}",
            f"║ Market Price      : {recommendation.market_price:.5f}",
            f"║ Entry / SL / TP   : {recommendation.entry:.5f} / {recommendation.stop_loss:.5f} / {recommendation.take_profit:.5f}",
            f"║ Risk/Reward       : {recommendation.risk_reward_ratio:.2f}",
            f"║ Confidence        : {recommendation.confidence:.2%}",
            f"║ Selected Strategy : {recommendation.selected_strategy_name}",
            f"║ News Status       : {recommendation.news_status}",
            f"║ News Effect       : {news_effect}",
            f"║ Timestamp (UTC)   : {recommendation.timestamp.isoformat()}",
            "╠════════════════════════════════ REASONS ══════════════════════════════════╣",
        ]
        lines.extend([f"║  • {reason}" for reason in recommendation.reasons] or ["║  • n/a"])
        lines.append("╚════════════════════════════════════════════════════════════════════════════╝")
        return "\n".join(lines)

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
