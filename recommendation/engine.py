"""Recommendation engine orchestration."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from core.indicators import atr
from core.mt5_client import MT5Client
from core.types import FinalRecommendation, SignalAction, StrategyScore, StrategySignal
from learning.optimizer import OptimizationResult, ParameterOptimizer
from news.base import NewsProvider
from news.filter import NewsFilter
from news.symbols import currencies_for_symbol
from recommendation.symbol_profile import profile_for_symbol, session_state
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
        profile = profile_for_symbol(symbol, self.settings)
        active_session_state = session_state(run_timestamp)
        spread_state, spread_value = "unknown", 0.0
        market_price = 0.0

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
                    symbol_profile=profile.name,
                    session_state=active_session_state,
                    spread_state=spread_state,
                    spread_value=spread_value,
                )

            market_status, market_reason = self.mt5.detect_market_status(symbol, timeframe)
            market_status = self._normalize_market_status(market_status)
            if market_status != "open":
                reason = market_reason if market_status != "closed" else f"Market is closed for {symbol}: {market_reason}"
                return self._no_trade(
                    symbol,
                    timeframe,
                    reason,
                    "blocked" if market_status != "closed" else "clear",
                    market_status,
                    run_timestamp,
                    market_price,
                    self._mt5_connection_status(),
                    symbol_profile=profile.name,
                    session_state=active_session_state,
                    spread_state=spread_state,
                    spread_value=spread_value,
                )

            candles = self.mt5.get_ohlcv(symbol, timeframe, int(self.settings.get("app.data_bars", 500)))
            if candles.empty:
                return self._no_trade(
                    symbol,
                    timeframe,
                    self.mt5.status_message or f"No market data for {symbol}/{timeframe}",
                    "blocked",
                    market_status,
                    run_timestamp,
                    market_price,
                    self._mt5_connection_status(),
                    symbol_profile=profile.name,
                    session_state=active_session_state,
                    spread_state=spread_state,
                    spread_value=spread_value,
                )
            market_price = float(candles.iloc[-1]["close"])

            spread_state, spread_value, spread_block_reason = self._assess_spread(symbol, profile)
            if spread_block_reason:
                return self._no_trade(
                    symbol,
                    timeframe,
                    spread_block_reason,
                    "clear",
                    market_status,
                    run_timestamp,
                    market_price,
                    self._mt5_connection_status(),
                    rejection_reason=spread_block_reason,
                    symbol_profile=profile.name,
                    session_state=active_session_state,
                    spread_state=spread_state,
                    spread_value=spread_value,
                )

            blocked, news_status, reason, confidence_multiplier, next_event = self._news_gate(symbol, profile)
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
                    symbol_profile=profile.name,
                    session_state=active_session_state,
                    spread_state=spread_state,
                    spread_value=spread_value,
                    next_relevant_news_event=next_event,
                )

            volatility_state, volatility_multiplier, volatility_block_reason = self._assess_volatility(candles, profile)
            confidence_multiplier *= volatility_multiplier
            if volatility_block_reason:
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
                    symbol_profile=profile.name,
                    session_state=active_session_state,
                    spread_state=spread_state,
                    spread_value=spread_value,
                    volatility_state=volatility_state,
                    next_relevant_news_event=next_event,
                )

            session_blocked, session_multiplier, session_reason = self._assess_session(profile, active_session_state)
            confidence_multiplier *= session_multiplier
            if session_blocked:
                return self._no_trade(
                    symbol,
                    timeframe,
                    session_reason,
                    news_status,
                    market_status,
                    run_timestamp,
                    market_price,
                    self._mt5_connection_status(),
                    rejection_reason=session_reason,
                    symbol_profile=profile.name,
                    session_state=active_session_state,
                    spread_state=spread_state,
                    spread_value=spread_value,
                    volatility_state=volatility_state,
                    next_relevant_news_event=next_event,
                )

            strategy_outputs = self._run_strategies(symbol, timeframe, candles)
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
                    symbol_profile=profile.name,
                    session_state=active_session_state,
                    spread_state=spread_state,
                    spread_value=spread_value,
                )

            recommendation = self._aggregate(
                symbol=symbol,
                timeframe=timeframe,
                strategy_outputs=strategy_outputs,
                market_price=market_price,
                confidence_multiplier=confidence_multiplier,
                news_status=news_status,
                news_reason=reason,
                market_status=market_status,
                timestamp=run_timestamp,
                mt5_connection_status=self._mt5_connection_status(),
                symbol_profile=profile.name,
                session_state=active_session_state,
                spread_state=spread_state,
                spread_value=spread_value,
                volatility_state=volatility_state,
                next_relevant_news_event=next_event,
                session_reason=session_reason,
                min_confidence=profile.min_confidence,
                min_risk_reward=profile.min_risk_reward,
            )
            LOGGER.info("Final recommendation generated\n%s", self.format_for_terminal(recommendation))
            return recommendation
        finally:
            self.mt5.shutdown()

    def _run_strategies(self, symbol: str, timeframe: str, candles: pd.DataFrame) -> list[tuple[StrategySignal, StrategyScore | None]]:
        outputs: list[tuple[StrategySignal, StrategyScore | None]] = []
        grid_root = self.settings.get("learning.parameter_grid", {})
        symbol_grid_root = self.settings.get(f"learning.symbol_parameter_grid.{symbol.upper()}", {})
        optimization_enabled = bool(self.settings.get("learning.optimization_enabled", True))
        active_count = max(2, min(3, int(self.settings.get("learning.active_strategy_count", 2))))

        optimization_results = self._optimize_strategies(symbol, timeframe, candles, grid_root, symbol_grid_root, optimization_enabled)
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
                score = StrategyScore(strategy.name, float(opt.best_score), 0.0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, float(getattr(opt, "best_expectancy", 0.0)))

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
        timeframe: str,
        candles: pd.DataFrame,
        grid_root: dict[str, dict[str, list[Any]]],
        symbol_grid_root: dict[str, dict[str, list[Any]]],
        optimization_enabled: bool,
    ) -> dict[str, OptimizationResult]:
        if not optimization_enabled:
            return {}
        results: dict[str, OptimizationResult] = {}
        profile = profile_for_symbol(symbol, self.settings)
        for strategy in self.strategies:
            defaults = dict(self.settings.get(f"strategy.{strategy.name}", {}))
            profile_ranges = dict(profile.optimizer_ranges.get(strategy.name, {})) if getattr(profile, "optimizer_ranges", None) else {}
            grid = {
                **dict(grid_root.get(strategy.name, {})),
                **dict(symbol_grid_root.get(strategy.name, {})),
                **profile_ranges,
            }
            fixed = {k: v for k, v in defaults.items() if k not in grid}
            opt = self.optimizer.optimize(strategy, candles, grid, symbol, timeframe, fixed)
            if opt is not None:
                results[strategy.name] = opt
        return results

    def _active_strategy_names(self, optimization_results: dict[str, OptimizationResult], active_count: int, optimization_enabled: bool) -> set[str]:
        if optimization_enabled and optimization_results:
            ranked = sorted(optimization_results.values(), key=lambda item: item.best_score, reverse=True)
            return {item.strategy_name for item in ranked[:active_count]}
        return {strategy.name for strategy in self.strategies}

    def _news_gate(self, symbol: str, profile: Any) -> tuple[bool, str, str, float, dict[str, Any] | None]:
        now = self.mt5.now()
        try:
            events = self.news_provider.fetch_events(now - timedelta(hours=4), now + timedelta(hours=24))
        except Exception as exc:  # pragma: no cover
            LOGGER.warning("News provider failed; marking news status unknown: %s", exc)
            return False, "unknown", "News provider unavailable; decision generated without news confirmation", 1.0, None

        symbol_currencies = profile.news_sensitivity.get("currencies", currencies_for_symbol(symbol, self.settings.get("news.symbols_map", {})))
        next_event = self._next_relevant_event(now, events, symbol_currencies)
        block_before = int(profile.news_sensitivity.get("block_before_min", 30))
        reduce_before = int(profile.news_sensitivity.get("reduce_before_min", 60))
        reduce_multiplier = float(profile.news_sensitivity.get("reduce_confidence_multiplier", 0.75))
        block_windows = dict(profile.news_sensitivity.get("block_windows", {}))
        currency_windows = dict(profile.news_sensitivity.get("currency_windows", {}))

        if next_event is not None:
            event_impact = str(next_event.get("impact", "")).lower()
            event_currency = str(next_event.get("currency", "")).upper()
            if event_currency in currency_windows and isinstance(currency_windows[event_currency], dict):
                window_for_currency = currency_windows[event_currency]
                block_before = int(window_for_currency.get("block_before_min", block_before))
                reduce_before = int(window_for_currency.get("reduce_before_min", reduce_before))
                reduce_multiplier = float(window_for_currency.get("reduce_confidence_multiplier", reduce_multiplier))
            if event_impact in block_windows and isinstance(block_windows[event_impact], dict):
                impact_window = block_windows[event_impact]
                block_before = int(impact_window.get("block_before_min", block_before))
                reduce_before = int(impact_window.get("reduce_before_min", reduce_before))
                reduce_multiplier = float(impact_window.get("reduce_confidence_multiplier", reduce_multiplier))

        if next_event is not None and next_event["impact"] in {"high", "red"}:
            minutes = float(next_event["minutes_to_event"])
            if minutes <= block_before:
                reason = f"High-impact news in {int(minutes)} minutes: {next_event['title']} ({next_event['currency']})"
                return True, "blocked", reason, 0.0, next_event
            if minutes <= reduce_before:
                reason = f"High-impact news in {int(minutes)} minutes: confidence reduced"
                return False, "reduced_confidence", reason, reduce_multiplier, next_event

        decision = self.news_filter.evaluate(now, events, symbol_currencies)
        if decision.decision == "block trading":
            return True, "blocked", decision.reason, decision.confidence_multiplier, next_event
        if decision.decision == "reduce confidence":
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
        symbol_profile: str = "default",
        session_state: str = "unknown",
        spread_state: str = "unknown",
        spread_value: float = 0.0,
        volatility_state: str = "normal",
        next_relevant_news_event: dict[str, Any] | None = None,
        session_reason: str = "",
        min_confidence: float | None = None,
        min_risk_reward: float | None = None,
    ) -> FinalRecommendation:
        if market_status != "open":
            return self._no_trade(symbol, timeframe, f"Market is not open ({market_status}); trade blocked", news_status, market_status, timestamp or datetime.utcnow(), market_price, self._mt5_connection_status(), symbol_profile=symbol_profile, session_state=session_state, spread_state=spread_state, spread_value=spread_value, volatility_state=volatility_state, next_relevant_news_event=next_relevant_news_event)
        if news_status == "blocked":
            return self._no_trade(symbol, timeframe, f"News filter blocked trading: {news_reason}", news_status, market_status, timestamp or datetime.utcnow(), market_price, self._mt5_connection_status(), symbol_profile=symbol_profile, session_state=session_state, spread_state=spread_state, spread_value=spread_value, volatility_state=volatility_state, next_relevant_news_event=next_relevant_news_event)

        buys = [item for item in strategy_outputs if item[0].action == SignalAction.BUY]
        sells = [item for item in strategy_outputs if item[0].action == SignalAction.SELL]
        if buys and sells:
            return self._no_trade(symbol, timeframe, "Conflicting strategy directions", news_status, market_status, timestamp or datetime.utcnow(), market_price, self._mt5_connection_status(), symbol_profile=symbol_profile, session_state=session_state, spread_state=spread_state, spread_value=spread_value)

        selected = buys if buys else sells
        confidence_weighted, weight_total = 0.0, 0.0
        entry_vals: list[float] = []
        sl_vals: list[float] = []
        tp_vals: list[float] = []
        reasons = [f"News status: {news_status}", f"News effect: {news_reason}", f"Session state: {session_state}", f"Spread state: {spread_state} ({spread_value:.2f})", f"Volatility state: {volatility_state}"]
        if session_reason:
            reasons.append(f"Session effect: {session_reason}")

        names: list[str] = []
        historical_scores = self._load_historical_scores(symbol, timeframe)
        recent_scores = self._load_recent_paper_scores(symbol, timeframe)
        score_weights = self._quality_score_weights()
        min_historical_score = float(self.settings.get("recommendation.min_historical_score", 40.0))
        reject_poor_historical = bool(self.settings.get("recommendation.reject_on_poor_historical", False))
        poor_hist_multiplier = max(0.0, min(1.0, float(self.settings.get("recommendation.poor_historical_confidence_multiplier", 0.7))))
        weak_cutoff = float(self.settings.get("learning.weak_strategy_score_cutoff", 1.0))
        weak_reduction = max(0.0, float(self.settings.get("learning.weak_strategy_confidence_multiplier", 0.75)))

        strategy_scores: list[float] = []
        recent_performance_scores: list[float] = []
        selected_historical_scores: list[float] = []
        selected_recent_scores: list[float] = []
        selected_combined_scores: list[float] = []

        for signal, score in selected:
            perf_weight = 1.0
            historical_score = historical_scores.get(signal.strategy_name)
            recent_score = recent_scores.get(signal.strategy_name)
            if historical_score is not None and historical_score < min_historical_score:
                if reject_poor_historical:
                    reasons.append(
                        f"{signal.strategy_name} rejected due to historical score {historical_score:.2f} < {min_historical_score:.2f}"
                    )
                    continue
                perf_weight *= poor_hist_multiplier
                reasons.append(
                    f"{signal.strategy_name} confidence reduced due to historical score {historical_score:.2f} < {min_historical_score:.2f}"
                )
            if score is not None and score.score < weak_cutoff:
                if score.score <= 0:
                    reasons.append(f"{signal.strategy_name} excluded due to weak recent performance score={score.score:.2f}")
                    continue
                perf_weight = weak_reduction
                reasons.append(f"{signal.strategy_name} confidence reduced due to weak recent performance score={score.score:.2f}")
            weight = max(1.0, score.score / 10.0) if score else 1.0
            confidence_weighted += signal.confidence * perf_weight * weight
            weight_total += weight
            entry_vals.append(signal.entry)
            sl_vals.append(signal.stop_loss)
            tp_vals.append(signal.take_profit)
            reasons.append(f"{signal.strategy_name}: {signal.reason}")
            names.append(signal.strategy_name)
            current_quality_score = float(signal.confidence * 100.0)
            combined_score = self._compute_combined_score(
                current_quality_score=current_quality_score,
                historical_score=historical_score,
                recent_score=recent_score,
                weights=score_weights,
            )
            selected_combined_scores.append(combined_score)
            reasons.append(
                f"{signal.strategy_name} diagnostics: current={current_quality_score:.2f}, historical={self._fmt_optional(historical_score)}, recent={self._fmt_optional(recent_score)}, combined={combined_score:.2f}"
            )
            if historical_score is not None:
                selected_historical_scores.append(float(historical_score))
            if recent_score is not None:
                selected_recent_scores.append(float(recent_score))
            if score is not None:
                strategy_scores.append(float(score.score))
                recent_performance_scores.append(float(score.win_rate))

        if not names:
            return self._no_trade(symbol, timeframe, "No strategies available after aggregation", news_status, market_status, timestamp or datetime.utcnow(), market_price, self._mt5_connection_status(), symbol_profile=symbol_profile, session_state=session_state, spread_state=spread_state, spread_value=spread_value)

        avg_entry, avg_sl, avg_tp = float(sum(entry_vals) / len(entry_vals)), float(sum(sl_vals) / len(sl_vals)), float(sum(tp_vals) / len(tp_vals))
        risk = abs(avg_entry - avg_sl)
        reward = abs(avg_tp - avg_entry)
        risk_reward_ratio = float(reward / risk) if risk > 0 else 0.0
        raw_confidence = float((confidence_weighted / weight_total) * confidence_multiplier)
        signal_strength = self._classify_signal_strength(raw_confidence, risk_reward_ratio, len(names), volatility_state)

        min_confidence = float(min_confidence if min_confidence is not None else self.settings.get("recommendation.min_confidence", 0.6))
        min_risk_reward = float(min_risk_reward if min_risk_reward is not None else self.settings.get("recommendation.min_risk_reward", 1.5))
        if raw_confidence < min_confidence:
            reason = f"Rejected: confidence {raw_confidence:.2f} below minimum {min_confidence:.2f}"
            return self._no_trade(symbol, timeframe, reason, news_status, market_status, timestamp or datetime.utcnow(), market_price, self._mt5_connection_status(), rejection_reason=reason, signal_strength=signal_strength, symbol_profile=symbol_profile, session_state=session_state, spread_state=spread_state, spread_value=spread_value, volatility_state=volatility_state, next_relevant_news_event=next_relevant_news_event)
        if risk_reward_ratio < min_risk_reward:
            reason = f"Rejected: risk/reward {risk_reward_ratio:.2f} below minimum {min_risk_reward:.2f}"
            return self._no_trade(symbol, timeframe, reason, news_status, market_status, timestamp or datetime.utcnow(), market_price, self._mt5_connection_status(), rejection_reason=reason, signal_strength=signal_strength, symbol_profile=symbol_profile, session_state=session_state, spread_state=spread_state, spread_value=spread_value, volatility_state=volatility_state, next_relevant_news_event=next_relevant_news_event)

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
            symbol_profile=symbol_profile,
            session_state=session_state,
            spread_state=spread_state,
            spread_value=spread_value,
            mt5_connection_status=mt5_connection_status or self._mt5_connection_status(),
            signal_strength=signal_strength,
            strategy_score=(sum(strategy_scores) / len(strategy_scores)) if strategy_scores else None,
            recent_performance_score=(sum(recent_performance_scores) / len(recent_performance_scores)) if recent_performance_scores else None,
            historical_score=(sum(selected_historical_scores) / len(selected_historical_scores)) if selected_historical_scores else None,
            recent_score=(sum(selected_recent_scores) / len(selected_recent_scores)) if selected_recent_scores else None,
            combined_score=(sum(selected_combined_scores) / len(selected_combined_scores)) if selected_combined_scores else None,
            volatility_state=volatility_state,
            next_relevant_news_event=next_relevant_news_event,
            next_relevant_news_countdown=self._format_news_countdown(next_relevant_news_event),
            next_news_event=next_relevant_news_event,
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
        symbol_profile: str = "default",
        session_state: str = "unknown",
        spread_state: str = "unknown",
        spread_value: float = 0.0,
        volatility_state: str = "normal",
        next_relevant_news_event: dict[str, Any] | None = None,
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
            symbol_profile=symbol_profile,
            session_state=session_state,
            spread_state=spread_state,
            spread_value=spread_value,
            mt5_connection_status=mt5_connection_status,
            signal_strength=signal_strength,
            rejection_reason=rejection_reason or reason,
            volatility_state=volatility_state,
            next_relevant_news_event=next_relevant_news_event,
            next_relevant_news_countdown=RecommendationEngine._format_news_countdown(next_relevant_news_event),
            next_news_event=next_relevant_news_event,
            reasons=[reason],
            timestamp=timestamp,
        )

    def _assess_volatility(self, candles: pd.DataFrame, profile: Any) -> tuple[str, float, str | None]:
        period = int(self.settings.get("recommendation.volatility.atr_period", 14))
        high_vol_confidence_multiplier = float(self.settings.get("recommendation.volatility.high_vol_confidence_multiplier", 0.85))
        low_vol_confidence_multiplier = float(self.settings.get("recommendation.volatility.low_vol_confidence_multiplier", 0.7))
        atr_series = atr(candles, period=period)
        if atr_series.empty or pd.isna(atr_series.iloc[-1]):
            return "normal", 1.0, None
        close = float(candles.iloc[-1]["close"])
        if close <= 0:
            return "normal", 1.0, None

        atr_pct = float(atr_series.iloc[-1] / close)
        if atr_pct < float(profile.atr_low_threshold):
            return "low", low_vol_confidence_multiplier, "Rejected: ATR volatility is too low for quality signals"
        if atr_pct > float(profile.atr_extreme_threshold):
            return "high", 0.0, "Rejected: ATR volatility is too high; market conditions are unstable"
        if atr_pct > float(profile.atr_high_threshold):
            return "high", high_vol_confidence_multiplier, None
        return "normal", 1.0, None

    def _assess_spread(self, symbol: str, profile: Any) -> tuple[str, float, str | None]:
        spread_value = float(getattr(self.mt5, "get_spread", lambda _symbol: 0.0)(symbol))
        if spread_value <= 0:
            return "unknown", 0.0, None
        if spread_value >= float(profile.spread_threshold):
            reason = f"Rejected: spread {spread_value:.2f} is above symbol threshold {float(profile.spread_threshold):.2f}"
            return "excessive", spread_value, reason
        if spread_value >= float(profile.spread_threshold) * float(profile.spread_elevated_ratio):
            return "elevated", spread_value, None
        return "normal", spread_value, None

    @staticmethod
    def _assess_session(profile: Any, active_session_state: str) -> tuple[bool, float, str]:
        preferred = {str(item).lower() for item in (profile.preferred_sessions or [])}
        if not preferred or active_session_state in preferred:
            return False, 1.0, "within preferred session window"
        if "overlap" in active_session_state and any(item in active_session_state for item in preferred):
            return False, 1.0, "within preferred overlap session window"
        if profile.session_outside_policy == "block":
            return True, 0.0, f"Rejected: session '{active_session_state}' is outside preferred sessions {sorted(preferred)}"
        multiplier = max(0.0, min(1.0, float(profile.session_confidence_multiplier)))
        return False, multiplier, f"Session '{active_session_state}' outside preferred sessions; confidence multiplier {multiplier:.2f} applied"

    @staticmethod
    def _classify_signal_strength(confidence: float, risk_reward: float, aligned_signals: int, volatility_state: str) -> str:
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

    def _next_relevant_event(self, now: datetime, events: list[Any], symbol_currencies: list[str]) -> dict[str, Any] | None:
        watched = {currency.upper() for currency in symbol_currencies}
        include_macro = "MACRO" in watched
        major_macro_currencies = {"USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD"}
        upcoming = [event for event in events if (str(event.currency).upper() in watched or (include_macro and str(event.currency).upper() in major_macro_currencies)) and event.event_time >= now]
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

    @staticmethod
    def _format_news_countdown(event_payload: dict[str, Any] | None) -> str | None:
        if not event_payload:
            return None
        minutes = float(event_payload.get("minutes_to_event", 0.0))
        if minutes >= 60:
            return f"{int(minutes // 60)}h {int(minutes % 60)}m"
        return f"{int(minutes)}m"

    def _mt5_connection_status(self) -> str:
        return "connected" if getattr(self.mt5, "connected", False) else "unavailable"

    @staticmethod
    def _normalize_market_status(status: str) -> str:
        return status if status in VALID_MARKET_STATUSES else "unavailable"

    @staticmethod
    def format_for_terminal(recommendation: FinalRecommendation) -> str:
        news_effect = next((reason.replace("News effect: ", "", 1) for reason in recommendation.reasons if reason.startswith("News effect: ")), "n/a")
        lines = [
            "╔══════════════════════════ FINAL RECOMMENDATION ══════════════════════════╗",
            f"║ Symbol            : {recommendation.symbol}",
            f"║ Timeframe         : {recommendation.timeframe}",
            f"║ Timestamp (UTC)   : {recommendation.timestamp.isoformat()}",
            f"║ Market Status     : {recommendation.market_status}",
            f"║ News Status       : {recommendation.news_status}",
            f"║ Symbol Profile    : {getattr(recommendation, 'symbol_profile', 'default')}",
            f"║ Session State     : {getattr(recommendation, 'session_state', 'unknown')}",
            f"║ Spread State      : {getattr(recommendation, 'spread_state', 'unknown')} ({getattr(recommendation, 'spread_value', 0.0):.2f})",
            f"║ Selected Strategy : {recommendation.selected_strategy}",
            f"║ Action            : {recommendation.action}",
            f"║ Market Price      : {recommendation.market_price:.5f}",
            f"║ Entry / SL / TP   : {recommendation.entry:.5f} / {recommendation.stop_loss:.5f} / {recommendation.take_profit:.5f}",
            f"║ Risk/Reward       : {recommendation.risk_reward:.2f}",
            f"║ Confidence        : {recommendation.confidence:.2%}",
            f"║ Signal Strength   : {getattr(recommendation, 'signal_strength', 'weak')}",
            f"║ Historical Score  : {RecommendationEngine._fmt_optional(getattr(recommendation, 'historical_score', None))}",
            f"║ Recent Score      : {RecommendationEngine._fmt_optional(getattr(recommendation, 'recent_score', None))}",
            f"║ Combined Score    : {RecommendationEngine._fmt_optional(getattr(recommendation, 'combined_score', None))}",
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
            handle.write(json.dumps({"symbol": symbol, "strategy": signal.strategy_name, "action": signal.action, "entry": signal.entry, "stop_loss": signal.stop_loss, "take_profit": signal.take_profit, "confidence": signal.confidence, "reason": signal.reason, "metadata": signal.metadata}) + "\n")

    def _load_historical_scores(self, symbol: str, timeframe: str) -> dict[str, float]:
        path = Path("state") / "best_params" / f"{symbol.upper()}_{timeframe.upper()}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        out: dict[str, float] = {}
        for strategy_name, item in payload.items():
            if not isinstance(item, dict):
                continue
            raw = item.get("historical_score")
            if raw is None:
                continue
            try:
                out[str(strategy_name)] = float(raw)
            except (TypeError, ValueError):
                continue
        return out

    def _load_recent_paper_scores(self, symbol: str, timeframe: str) -> dict[str, float]:
        path = Path("logs/paper_trades.csv")
        if not path.exists():
            return {}
        try:
            frame = pd.read_csv(path)
        except Exception:
            return {}
        if frame.empty:
            return {}
        symbol_col = frame.get("symbol")
        timeframe_col = frame.get("timeframe")
        strategy_col = frame.get("strategy")
        if symbol_col is None or timeframe_col is None or strategy_col is None:
            return {}
        scoped = frame[
            symbol_col.astype(str).str.upper().eq(symbol.upper())
            & timeframe_col.astype(str).str.upper().eq(timeframe.upper())
        ].copy()
        if scoped.empty:
            return {}
        recent_trade_window = int(self.settings.get("recommendation.recent_score_trade_window", 30))
        scored: dict[str, float] = {}
        for name, group in scoped.groupby(strategy_col.astype(str)):
            latest = group.tail(recent_trade_window)
            wins = pd.to_numeric(latest.get("is_win"), errors="coerce").fillna(0.0)
            score = float(wins.mean() * 100.0) if not wins.empty else 0.0
            scored[str(name)] = score
        return scored

    def _quality_score_weights(self) -> dict[str, float]:
        current = float(self.settings.get("recommendation.quality_weight_current_signal", 0.5))
        historical = float(self.settings.get("recommendation.quality_weight_historical_score", 0.3))
        recent = float(self.settings.get("recommendation.quality_weight_recent_score", 0.2))
        return {"current": current, "historical": historical, "recent": recent}

    @staticmethod
    def _compute_combined_score(
        *,
        current_quality_score: float,
        historical_score: float | None,
        recent_score: float | None,
        weights: dict[str, float],
    ) -> float:
        components = [("current", current_quality_score)]
        if historical_score is not None:
            components.append(("historical", historical_score))
        if recent_score is not None:
            components.append(("recent", recent_score))
        weight_sum = sum(max(0.0, float(weights.get(name, 0.0))) for name, _ in components)
        if weight_sum <= 0:
            return float(current_quality_score)
        return float(sum(value * (max(0.0, float(weights.get(name, 0.0))) / weight_sum) for name, value in components))

    @staticmethod
    def _fmt_optional(value: float | None) -> str:
        if value is None:
            return "n/a"
        return f"{float(value):.2f}"
