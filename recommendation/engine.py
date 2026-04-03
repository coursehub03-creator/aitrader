"""Recommendation engine orchestration."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from core.mt5_client import MT5Client
from core.indicators import atr
from core.types import FinalRecommendation, SignalAction, StrategyScore, StrategySignal
from learning.optimizer import OptimizationResult, ParameterOptimizer
from news.base import NewsProvider
from news.filter import NewsFilter
from news.symbols import currencies_for_symbol
from strategy.base import TradingStrategy

LOGGER = logging.getLogger(__name__)
VALID_MARKET_STATUSES = {"open", "closed", "unavailable", "mt5_unavailable"}


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
                    self._mt5_connection_status(),
                )

            market_status, market_reason = self.mt5.detect_market_status(symbol, timeframe)
            market_status = self._normalize_market_status(market_status)
            if market_status == "mt5_unavailable":
                return self._no_trade(
                    symbol,
                    timeframe,
                    market_reason,
                    "blocked",
                    market_status,
                    run_timestamp,
                    market_price,
                    self._mt5_connection_status(),
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
                    self._mt5_connection_status(),
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
                    self._mt5_connection_status(),
                )

            candles = self.mt5.get_ohlcv(
                symbol,
                timeframe,
                int(self.settings.get("app.data_bars", 500)),
            )
            if candles.empty:
                reason = self.mt5.status_message or f"No market data for {symbol}/{timeframe}"
                return self._no_trade(
                    symbol,
                    timeframe,
                    reason,
                    "blocked",
                    market_status,
                    run_timestamp,
                    market_price,
                    self._mt5_connection_status(),
                )
            market_price = float(candles.iloc[-1]["close"])

            blocked, news_status, reason, confidence_multiplier, next_news_event = self._news_gate(symbol)
            if blocked:
                return self._no_trade(
                    symbol,
                    timeframe,
                    reason,
                    news_status,
                    market_status,
                    run_timestamp,
                    market_price,
                    self._mt5_connection_status(),
                    rejection_reason=reason,
                    next_news_event=next_news_event,
                )

            volatility_state, volatility_multiplier, volatility_block_reason = self._assess_volatility(candles)
            confidence_multiplier *= volatility_multiplier
            if volatility_block_reason is not None:
                return self._no_trade(
                    symbol,
                    timeframe,
                    volatility_block_reason,
                    news_status,
                    market_status,
                    run_timestamp,
                    market_price,
                    self._mt5_connection_status(),
                    rejection_reason=volatility_block_reason,
                    volatility_state=volatility_state,
                    next_news_event=next_news_event,
                )

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
                    self._mt5_connection_status(),
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
                self._mt5_connection_status(),
                volatility_state=volatility_state,
                next_news_event=next_news_event,
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
                score = StrategyScore(
                    strategy_name=strategy.name,
                    score=float(opt.best_score),
                    net_pnl=0.0,
                    trades=0,
                    max_drawdown=0.0,
                    win_rate=0.0,
                    loss_rate=0.0,
                    average_pnl=0.0,
                    profit_factor=0.0,
                    expectancy=float(getattr(opt, "best_expectancy", 0.0)),
                )

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

    def _news_gate(self, symbol: str) -> tuple[bool, str, str, float, dict[str, Any] | None]:
        now = self.mt5.now()
        try:
            events = self.news_provider.fetch_events(
                now - timedelta(hours=4),
                now + timedelta(hours=24),
            )
        except Exception as exc:  # defensive fallback for custom providers
            LOGGER.warning("News provider failed; marking news status unknown: %s", exc)
            return False, "unknown", "News provider unavailable; decision generated without news confirmation", 1.0, None

        symbol_currencies = currencies_for_symbol(symbol, self.settings.get("news.symbols_map", {}))
        next_event = self._next_relevant_event(now, events, symbol_currencies)
        if next_event is not None and next_event["impact"] in {"high", "red"}:
            minutes = float(next_event["minutes_to_event"])
            if minutes <= 30:
                reason = f"High-impact news in {int(minutes)} minutes: {next_event['title']} ({next_event['currency']})"
                return True, "blocked", reason, 0.0, next_event
            if minutes <= 60:
                reason = f"High-impact news in {int(minutes)} minutes: confidence reduced"
                return False, "reduced_confidence", reason, 0.75, next_event

        decision = self.news_filter.evaluate(now, events, symbol_currencies)

        if decision.decision == "block trading":
            LOGGER.info("Recommendation blocked by news filter: %s", decision.reason)
            return True, "blocked", decision.reason, decision.confidence_multiplier, next_event

        if decision.decision == "reduce confidence":
            LOGGER.info("Recommendation confidence reduced by news filter: %s", decision.reason)
            return False, "reduced_confidence", decision.reason, decision.confidence_multiplier, next_event

        return False, "clear", decision.reason, decision.confidence_multiplier, next_event

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
        mt5_connection_status: str | None = None,
        volatility_state: str = "normal",
        next_news_event: dict[str, Any] | None = None,
    ) -> FinalRecommendation:
        if market_status != "open":
            return self._no_trade(
                symbol,
                timeframe,
                f"Market is not open ({market_status}); trade blocked",
                news_status,
                market_status,
                timestamp or datetime.utcnow(),
                market_price,
                self._mt5_connection_status(),
                volatility_state=volatility_state,
                next_news_event=next_news_event,
            )
        if news_status == "blocked":
            return self._no_trade(
                symbol,
                timeframe,
                f"News filter blocked trading: {news_reason}",
                news_status,
                market_status,
                timestamp or datetime.utcnow(),
                market_price,
                self._mt5_connection_status(),
                volatility_state=volatility_state,
                next_news_event=next_news_event,
            )

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
                self._mt5_connection_status(),
            )

        selected = buys if buys else sells

        confidence_weighted = 0.0
        weight_total = 0.0

        entry_vals: list[float] = []
        sl_vals: list[float] = []
        tp_vals: list[float] = []
        reasons: list[str] = [f"News status: {news_status}", f"News effect: {news_reason}"]
        reasons.append(f"Volatility state: {volatility_state}")
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
                self._mt5_connection_status(),
            )

        avg_entry = float(sum(entry_vals) / len(entry_vals))
        avg_sl = float(sum(sl_vals) / len(sl_vals))
        avg_tp = float(sum(tp_vals) / len(tp_vals))
        risk = abs(avg_entry - avg_sl)
        reward = abs(avg_tp - avg_entry)
        risk_reward_ratio = float(reward / risk) if risk > 0 else 0.0
        raw_confidence = float((confidence_weighted / weight_total) * confidence_multiplier)
        aligned_signals = len(names)

        signal_strength = self._classify_signal_strength(
            confidence=raw_confidence,
            risk_reward=risk_reward_ratio,
            aligned_signals=aligned_signals,
            volatility_state=volatility_state,
        )

        min_confidence = float(self.settings.get("recommendation.min_confidence", 0.6))
        min_risk_reward = float(self.settings.get("recommendation.min_risk_reward", 1.5))
        if raw_confidence < min_confidence:
            reason = f"Rejected: confidence {raw_confidence:.2f} below minimum {min_confidence:.2f}"
            return self._no_trade(
                symbol,
                timeframe,
                reason,
                news_status,
                market_status,
                timestamp or datetime.utcnow(),
                market_price,
                self._mt5_connection_status(),
                rejection_reason=reason,
                signal_strength=signal_strength,
                volatility_state=volatility_state,
                next_news_event=next_news_event,
            )
        if risk_reward_ratio < min_risk_reward:
            reason = f"Rejected: risk/reward {risk_reward_ratio:.2f} below minimum {min_risk_reward:.2f}"
            return self._no_trade(
                symbol,
                timeframe,
                reason,
                news_status,
                market_status,
                timestamp or datetime.utcnow(),
                market_price,
                self._mt5_connection_status(),
                rejection_reason=reason,
                signal_strength=signal_strength,
                volatility_state=volatility_state,
                next_news_event=next_news_event,
            )
        if aligned_signals == 1 and signal_strength == "weak":
            reason = "Rejected: only one weak strategy signal detected; confluence required"
            return self._no_trade(
                symbol,
                timeframe,
                reason,
                news_status,
                market_status,
                timestamp or datetime.utcnow(),
                market_price,
                self._mt5_connection_status(),
                rejection_reason=reason,
                signal_strength=signal_strength,
                volatility_state=volatility_state,
                next_news_event=next_news_event,
            )
        if aligned_signals > 1:
            reasons.append(f"Confluence confirmed across {aligned_signals} aligned strategies")
        else:
            reasons.append("Single-strategy signal (lower confluence)")

        return FinalRecommendation(
            symbol=symbol,
            timeframe=timeframe,
            action=selected[0][0].action,
            market_price=market_price,
            entry=avg_entry,
            stop_loss=avg_sl,
            take_profit=avg_tp,
            risk_reward=risk_reward_ratio,
            confidence=raw_confidence,
            selected_strategy=names[0] if len(names) == 1 else "+".join(names),
            market_status=market_status,
            news_status=news_status,
            mt5_connection_status=mt5_connection_status or self._mt5_connection_status(),
            signal_strength=signal_strength,
            volatility_state=volatility_state,
            next_news_event=next_news_event,
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
        mt5_connection_status: str = "unknown",
        rejection_reason: str | None = None,
        signal_strength: str = "weak",
        volatility_state: str = "normal",
        next_news_event: dict[str, Any] | None = None,
    ) -> FinalRecommendation:
        return FinalRecommendation(
            symbol=symbol,
            timeframe=timeframe,
            action=SignalAction.NO_TRADE,
            market_price=market_price,
            entry=0.0,
            stop_loss=0.0,
            take_profit=0.0,
            risk_reward=0.0,
            confidence=0.0,
            selected_strategy="none",
            market_status=market_status,
            news_status=news_status,
            mt5_connection_status=mt5_connection_status,
            signal_strength=signal_strength,
            rejection_reason=rejection_reason or reason,
            volatility_state=volatility_state,
            next_news_event=next_news_event,
            reasons=[reason],
            timestamp=timestamp,
        )

    def _assess_volatility(self, candles: pd.DataFrame) -> tuple[str, float, str | None]:
        period = int(self.settings.get("recommendation.volatility.atr_period", 14))
        low_atr_pct = float(self.settings.get("recommendation.volatility.low_atr_pct", 0.0005))
        high_atr_pct = float(self.settings.get("recommendation.volatility.high_atr_pct", 0.005))
        extreme_high_atr_pct = float(self.settings.get("recommendation.volatility.extreme_high_atr_pct", high_atr_pct * 1.5))
        high_vol_confidence_multiplier = float(
            self.settings.get("recommendation.volatility.high_vol_confidence_multiplier", 0.85)
        )
        low_vol_confidence_multiplier = float(
            self.settings.get("recommendation.volatility.low_vol_confidence_multiplier", 0.7)
        )

        atr_series = atr(candles, period=period)
        if atr_series.empty or pd.isna(atr_series.iloc[-1]):
            return "normal", 1.0, None
        close = float(candles.iloc[-1]["close"])
        if close <= 0:
            return "normal", 1.0, None

        atr_pct = float(atr_series.iloc[-1] / close)
        if atr_pct < low_atr_pct:
            return "low", low_vol_confidence_multiplier, "Rejected: ATR volatility is too low for quality signals"
        if atr_pct > extreme_high_atr_pct:
            return "high", 0.0, "Rejected: ATR volatility is too high; market conditions are unstable"
        if atr_pct > high_atr_pct:
            return "high", high_vol_confidence_multiplier, None
        return "normal", 1.0, None

    @staticmethod
    def _classify_signal_strength(
        confidence: float,
        risk_reward: float,
        aligned_signals: int,
        volatility_state: str,
    ) -> str:
        score = 0
        score += 2 if confidence >= 0.75 else 1 if confidence >= 0.6 else 0
        score += 2 if risk_reward >= 2.0 else 1 if risk_reward >= 1.5 else 0
        score += 2 if aligned_signals >= 2 else 0
        score += 1 if volatility_state == "normal" else 0
        if score >= 6:
            return "strong"
        if score >= 3:
            return "medium"
        return "weak"

    def _next_relevant_event(
        self,
        now: datetime,
        events: list[Any],
        symbol_currencies: list[str],
    ) -> dict[str, Any] | None:
        watched = {currency.upper() for currency in symbol_currencies}
        include_macro = "MACRO" in watched
        major_macro_currencies = {"USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD"}
        upcoming: list[Any] = []
        for event in events:
            event_currency = str(event.currency).upper()
            if event_currency not in watched and not (include_macro and event_currency in major_macro_currencies):
                continue
            if event.event_time < now:
                continue
            upcoming.append(event)
        if not upcoming:
            return None
        nearest = min(upcoming, key=lambda event: event.event_time)
        delta_min = max(0.0, (nearest.event_time - now).total_seconds() / 60.0)
        return {
            "title": nearest.title,
            "currency": nearest.currency,
            "impact": nearest.impact.lower(),
            "event_time_utc": nearest.event_time.isoformat(),
            "minutes_to_event": round(delta_min, 1),
        }

    def _mt5_connection_status(self) -> str:
        return "connected" if getattr(self.mt5, "connected", False) else "unavailable"

    @staticmethod
    def _normalize_market_status(status: str) -> str:
        if status in VALID_MARKET_STATUSES:
            return status
        return "unavailable"

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
            f"║ Symbol            : {recommendation.symbol}",
            f"║ Timeframe         : {recommendation.timeframe}",
            f"║ Timestamp (UTC)   : {recommendation.timestamp.isoformat()}",
            f"║ Market Status     : {recommendation.market_status}",
            f"║ News Status       : {recommendation.news_status}",
            f"║ Selected Strategy : {recommendation.selected_strategy}",
            f"║ Action            : {recommendation.action}",
            f"║ Market Price      : {recommendation.market_price:.5f}",
            f"║ Entry / SL / TP   : {recommendation.entry:.5f} / {recommendation.stop_loss:.5f} / {recommendation.take_profit:.5f}",
            f"║ Risk/Reward       : {recommendation.risk_reward:.2f}",
            f"║ Confidence        : {recommendation.confidence:.2%}",
            f"║ Signal Strength   : {getattr(recommendation, 'signal_strength', 'weak')}",
            f"║ Volatility State  : {getattr(recommendation, 'volatility_state', 'normal')}",
            f"║ Rejection Reason  : {getattr(recommendation, 'rejection_reason', None) or 'n/a'}",
            f"║ News Effect       : {news_effect}",
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
