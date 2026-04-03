"""Service layer for Streamlit dashboard integration."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from app.main import build_engine
from config_loader import Settings, load_settings
from core.mt5_client import MT5Client
from core.paper_trading import PaperTrader, TradeStore
from core.types import FinalRecommendation, PaperTradeResult, SignalAction
from learning.evaluator import PerformanceEvaluator
from learning.historical_data import HistoricalDataPipeline
from learning.persistence import LearningPersistence
from learning.unified import UnifiedLearningScorer
from monitoring.alerts import AlertPolicy, AlertCooldownStore
from notification.telegram_notifier import TelegramNotifier
from strategy.registry import create_default_strategies
from ui.learning_center import (
    compute_learning_health_summary,
    extract_best_configuration_per_symbol,
    load_learning_data,
    prepare_state_changes,
)

LOGGER = logging.getLogger(__name__)


class DashboardService:
    """Thin adapter that reuses backend modules for UI flows."""

    def __init__(self, settings_path: str = "config/settings.yaml") -> None:
        self.settings_path = settings_path
        self.settings: Settings = load_settings(settings_path)
        self.engine = build_engine(self.settings)
        self.paper_trader = PaperTrader()
        self.trade_store = TradeStore()
        self.persistence = LearningPersistence()
        self.unified_scorer = UnifiedLearningScorer(
            historical_weight=float(self.settings.get("learning.historical_weight", 0.4)),
            recent_weight=float(self.settings.get("learning.recent_weight", 0.6)),
            min_sample_size=int(self.settings.get("learning.min_promotion_sample", 15)),
            max_drawdown=float(self.settings.get("learning.max_promotion_drawdown", 7.5)),
            min_expectancy=float(self.settings.get("learning.min_promotion_expectancy", 0.0)),
            degradation_threshold=float(self.settings.get("learning.degradation_threshold", 25.0)),
        )
        self.history_pipeline = HistoricalDataPipeline(self._build_mt5_client(), persistence=self.persistence)
        self.recent_recommendations_path = Path("logs/ui_recent_recommendations.csv")
        self.alert_history_path = Path("logs/ui_alert_history.csv")
        self.alert_state_path = Path("logs/ui_alert_state.json")
        self.trade_csv_path = Path("logs/paper_trades.csv")
        self.trade_sqlite_path = Path("logs/paper_trades.sqlite3")
        self.learning_dir = Path("logs/learning")
        self.learning_metadata_path = self.learning_dir / "learning_metadata.json"
        self._trade_columns = [
            *TradeStore.REQUIRED_COLUMNS,
            "timeframe",
            "strategy",
            "result",
            "signal_strength",
            "market_conditions",
            "news_status",
            "spread_state",
            "session_state",
        ]

    @staticmethod
    def _safe_read_csv(path: Path, columns: list[str], *, dataset_name: str) -> pd.DataFrame:
        try:
            frame = pd.read_csv(path)
        except (FileNotFoundError, pd.errors.EmptyDataError):
            return pd.DataFrame(columns=columns)
        except pd.errors.ParserError as exc:
            LOGGER.warning("Dataset '%s' is malformed at %s: %s", dataset_name, path, exc)
            return pd.DataFrame(columns=columns)
        except Exception as exc:  # pragma: no cover - defensive fallback
            LOGGER.warning("Dataset '%s' could not be loaded from %s: %s", dataset_name, path, exc)
            return pd.DataFrame(columns=columns)

        for column in columns:
            if column not in frame.columns:
                frame[column] = ""
        return frame[columns]

    def fetch_historical_data(
        self,
        symbol: str,
        timeframe: str,
        lookback_days: int,
    ) -> dict[str, Any]:
        mt5 = self._build_mt5_client()
        pipeline = HistoricalDataPipeline(mt5, persistence=self.persistence)
        try:
            mt5.connect()
            frame, path = pipeline.fetch_and_store_days(symbol=symbol, timeframe=timeframe, lookback_days=int(lookback_days))
            if frame.empty:
                return {
                    "success": False,
                    "symbol": symbol.upper(),
                    "timeframe": timeframe.upper(),
                    "lookback_days": int(lookback_days),
                    "candles_fetched": 0,
                    "date_start": "",
                    "date_end": "",
                    "storage_path": "",
                    "status_message": mt5.status_message or "No historical data available.",
                }
            times = pd.to_datetime(frame["time"], errors="coerce").dropna()
            return {
                "success": True,
                "symbol": symbol.upper(),
                "timeframe": timeframe.upper(),
                "lookback_days": int(lookback_days),
                "candles_fetched": int(len(frame)),
                "date_start": times.min().isoformat() if not times.empty else "",
                "date_end": times.max().isoformat() if not times.empty else "",
                "storage_path": str(path),
                "status_message": f"Fetched {len(frame)} candles successfully.",
            }
        except ValueError as exc:
            return {
                "success": False,
                "symbol": symbol.upper(),
                "timeframe": timeframe.upper(),
                "lookback_days": int(lookback_days),
                "candles_fetched": 0,
                "date_start": "",
                "date_end": "",
                "storage_path": "",
                "status_message": str(exc),
            }
        finally:
            mt5.shutdown()

    def historical_data_summary(self) -> pd.DataFrame:
        return self.history_pipeline.summary()

    def refresh_settings(self) -> None:
        self.settings = load_settings(self.settings_path)
        self.engine = build_engine(self.settings)

    def evaluate_and_send_alert(self, recommendation: FinalRecommendation) -> tuple[str, str, bool, str]:
        policy = AlertPolicy(
            min_confidence=float(
                self.settings.get(
                    "monitoring.minimum_confidence_for_alert",
                    self.settings.get("recommendation.min_confidence", 0.6),
                )
            ),
            min_risk_reward=float(self.settings.get("recommendation.min_risk_reward", 1.5)),
            min_signal_strength=str(self.settings.get("monitoring.minimum_signal_strength_for_alert", "strong")),
        )
        qualifies, qualify_reason = policy.qualifies(recommendation)
        alert_type = "strong_trade_alert"
        if not qualifies:
            if not bool(self.settings.get("monitoring.send_rejected_alerts", False)):
                return "suppressed", qualify_reason, False, alert_type
            rejection_map = {
                "market_closed_or_unavailable": "trade_blocked_by_market_closed",
                "news_blocked": "trade_blocked_by_news",
                "confidence_below_threshold": "trade_blocked_by_filters",
                "risk_reward_below_threshold": "trade_blocked_by_filters",
                "weak_or_medium_signal": "trade_blocked_by_filters",
            }
            alert_type = rejection_map.get(qualify_reason, "rejected_signal_alert")
            notifier = TelegramNotifier.from_settings(self.settings)
            sent, send_reason = notifier.send_recommendation_alert(recommendation, alert_type=alert_type)
            if sent:
                return "sent", send_reason, True, alert_type
            return "failed", send_reason, False, alert_type

        cooldown = AlertCooldownStore(
            self.alert_state_path,
            cooldown_seconds=int(self.settings.get("monitoring.alert_cooldown_seconds", 900)),
        )
        key = cooldown.build_key(recommendation)
        can_send, cooldown_reason = cooldown.can_send(key, datetime.now(tz=timezone.utc))
        if not can_send:
            LOGGER.info("Dashboard alert suppressed by cooldown for %s: %s", recommendation.symbol, cooldown_reason)
            return "suppressed", cooldown_reason, False, alert_type

        notifier = TelegramNotifier.from_settings(self.settings)
        sent, send_reason = notifier.send_recommendation_alert(recommendation, alert_type=alert_type)
        if sent:
            cooldown.mark_sent(key, datetime.now(tz=timezone.utc))
            return "sent", send_reason, True, alert_type
        return "failed", send_reason, False, alert_type

    @staticmethod
    def recommendation_to_record(recommendation: FinalRecommendation) -> dict[str, Any]:
        action = recommendation.action.value if hasattr(recommendation.action, "value") else recommendation.action
        return {
            "timestamp": recommendation.timestamp.replace(tzinfo=timezone.utc).isoformat(),
            "symbol": recommendation.symbol,
            "timeframe": recommendation.timeframe,
            "market_status": recommendation.market_status,
            "mt5_connection_status": recommendation.mt5_connection_status,
            "news_status": recommendation.news_status,
            "symbol_profile": recommendation.symbol_profile,
            "session_state": recommendation.session_state,
            "spread_state": recommendation.spread_state,
            "spread_value": recommendation.spread_value,
            "selected_strategy": recommendation.selected_strategy,
            "action": action,
            "entry": recommendation.entry,
            "stop_loss": recommendation.stop_loss,
            "take_profit": recommendation.take_profit,
            "confidence": recommendation.confidence,
            "risk_reward": recommendation.risk_reward,
            "signal_strength": recommendation.signal_strength,
            "rejection_reason": recommendation.rejection_reason or "",
            "volatility_state": recommendation.volatility_state,
            "next_relevant_news_event": json.dumps(recommendation.next_relevant_news_event or {}),
            "next_relevant_news_countdown": recommendation.next_relevant_news_countdown or "",
            "reasons": " | ".join(recommendation.reasons),
        }

    def connection_status(self, symbol: str, timeframe: str) -> tuple[str, str]:
        mt5 = self._build_mt5_client()
        mt5.connect()
        try:
            if not mt5.connected:
                return "mt5_unavailable", mt5.status_message
            status, reason = mt5.detect_market_status(symbol, timeframe)
            return status, reason
        finally:
            mt5.shutdown()

    def generate_recommendation(self, symbol: str, timeframe: str) -> FinalRecommendation:
        try:
            recommendation = self.engine.generate(symbol=symbol.upper(), timeframe=timeframe.upper())
        except Exception as exc:  # defensive UI resilience
            recommendation = FinalRecommendation(
                symbol=symbol.upper(),
                timeframe=timeframe.upper(),
                action=SignalAction.NO_TRADE,
                market_price=0.0,
                entry=0.0,
                stop_loss=0.0,
                take_profit=0.0,
                risk_reward=0.0,
                confidence=0.0,
                selected_strategy="none",
                market_status="mt5_unavailable",
                news_status="unknown",
                mt5_connection_status="unavailable",
                signal_strength="weak",
                rejection_reason=f"Runtime error while generating recommendation: {exc}",
                volatility_state="normal",
                next_news_event=None,
                reasons=[f"Runtime error while generating recommendation: {exc}"],
                timestamp=datetime.utcnow(),
            )
        self.persist_recommendation(recommendation)
        return recommendation

    def persist_recommendation(self, recommendation: FinalRecommendation) -> None:
        row = pd.DataFrame([self.recommendation_to_record(recommendation)])
        self.recent_recommendations_path.parent.mkdir(parents=True, exist_ok=True)
        if self.recent_recommendations_path.exists():
            existing = self._safe_read_csv(
                self.recent_recommendations_path,
                list(row.columns),
                dataset_name="ui_recent_recommendations",
            )
            combined = pd.concat([existing, row], ignore_index=True)
        else:
            combined = row

        combined = combined.tail(500)
        combined.to_csv(self.recent_recommendations_path, index=False)

    def persist_alert_event(
        self,
        recommendation: FinalRecommendation,
        status: str,
        reason: str,
        triggered: bool,
        alert_type: str,
    ) -> None:
        row = pd.DataFrame(
            [
                {
                    "timestamp": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
                    "symbol": recommendation.symbol,
                    "timeframe": recommendation.timeframe,
                    "alert_type": alert_type,
                    "message_summary": f"{recommendation.symbol} {recommendation.timeframe} {recommendation.action} {recommendation.signal_strength}",
                    "sent": status == "sent",
                    "suppressed": status == "suppressed",
                    "suppression_reason": reason if status == "suppressed" else "",
                    "status": status,
                    "reason": reason,
                    "triggered": triggered,
                }
            ]
        )
        self.alert_history_path.parent.mkdir(parents=True, exist_ok=True)
        if self.alert_history_path.exists():
            existing = self._safe_read_csv(self.alert_history_path, list(row.columns), dataset_name="ui_alert_history")
            combined = pd.concat([existing, row], ignore_index=True)
        else:
            combined = row
        combined.tail(500).to_csv(self.alert_history_path, index=False)

    def recent_alert_events(self, limit: int = 50) -> pd.DataFrame:
        frame = self._safe_read_csv(
            self.alert_history_path,
            [
                "timestamp",
                "symbol",
                "timeframe",
                "alert_type",
                "message_summary",
                "sent",
                "suppressed",
                "suppression_reason",
                "status",
                "reason",
                "triggered",
            ],
            dataset_name="ui_alert_history",
        )
        return frame.tail(limit).iloc[::-1].reset_index(drop=True)

    def recent_recommendations(self, limit: int = 50) -> pd.DataFrame:
        frame = self._safe_read_csv(
            self.recent_recommendations_path,
            list(self.recommendation_to_record(self._empty_recommendation()).keys()),
            dataset_name="ui_recent_recommendations",
        )
        return frame.tail(limit).iloc[::-1].reset_index(drop=True)

    def refresh_market_data(self, symbol: str, timeframe: str, bars: int = 300) -> tuple[pd.DataFrame, str]:
        mt5 = self._build_mt5_client()
        mt5.connect()
        try:
            if not mt5.connected:
                return pd.DataFrame(), mt5.status_message
            candles = mt5.get_ohlcv(symbol.upper(), timeframe.upper(), bars)
            if candles.empty:
                return pd.DataFrame(), mt5.status_message or "No market data returned"
            return candles, "Market data refreshed"
        finally:
            mt5.shutdown()

    def recent_news_events(self, symbol: str, lookback_hours: int = 2, lookahead_hours: int = 24) -> list[dict[str, Any]]:
        now = datetime.now(tz=timezone.utc)
        try:
            events = self.engine.news_provider.fetch_events(now - timedelta(hours=lookback_hours), now + timedelta(hours=lookahead_hours))
        except Exception as exc:  # pragma: no cover - defensive streamlit behavior
            LOGGER.warning("Could not fetch chart news events for %s: %s", symbol, exc)
            return []

        symbol_upper = symbol.upper()
        mapped = []
        for event in events:
            mapped.append(
                {
                    "event_id": getattr(event, "event_id", ""),
                    "title": getattr(event, "title", ""),
                    "currency": getattr(event, "currency", ""),
                    "impact": str(getattr(event, "impact", "")),
                    "event_time": getattr(event, "event_time", now),
                    "source": getattr(event, "source", ""),
                }
            )
        if not mapped:
            return []

        symbol_currencies = set()
        if len(symbol_upper) >= 6:
            symbol_currencies = {symbol_upper[:3], symbol_upper[3:6]}
        return [evt for evt in mapped if not symbol_currencies or str(evt.get("currency", "")).upper() in symbol_currencies]

    def run_optimizer(self, symbol: str, timeframe: str) -> pd.DataFrame:
        mt5 = self._build_mt5_client()
        mt5.connect()
        try:
            if not mt5.connected:
                return pd.DataFrame([{"error": mt5.status_message}])

            bars = int(self.settings.get("app.data_bars", 500))
            candles = mt5.get_ohlcv(symbol.upper(), timeframe.upper(), bars)
            if candles.empty:
                return pd.DataFrame([{"error": mt5.status_message or "No data for optimizer"}])

            grid_root = self.settings.get("learning.parameter_grid", {})
            rows: list[dict[str, Any]] = []
            for strategy in create_default_strategies():
                defaults = dict(self.settings.get(f"strategy.{strategy.name}", {}))
                grid = dict(grid_root.get(strategy.name, {}))
                fixed = {k: v for k, v in defaults.items() if k not in grid}
                result = self.engine.optimizer.optimize(strategy, candles, grid, symbol.upper(), fixed)
                if result is None:
                    continue
                rows.append(
                    {
                        "strategy": result.strategy_name,
                        "score": result.best_score,
                        "tested_combinations": result.tested_combinations,
                        "best_params": json.dumps(result.best_params),
                        "report_path": result.report_path,
                    }
                )

            if not rows:
                return pd.DataFrame([{"info": "No optimizer results (insufficient data or no valid candidates)."}])
            table = pd.DataFrame(rows).sort_values("score", ascending=False).reset_index(drop=True)
            self._persist_optimizer_snapshot(table, symbol.upper(), timeframe.upper())
            self._persist_learning_metadata(last_optimization_run=datetime.now(tz=timezone.utc).isoformat(timespec="seconds"))
            return table
        finally:
            mt5.shutdown()

    def simulate_paper_trade_cycle(self, symbol: str, timeframe: str) -> tuple[pd.DataFrame, str]:
        mt5 = self._build_mt5_client()
        mt5.connect()
        try:
            if not mt5.connected:
                return pd.DataFrame(), mt5.status_message

            lookahead = int(self.settings.get("learning.lookahead_bars", 8))
            bars = max(200, int(self.settings.get("app.data_bars", 500)))
            candles = mt5.get_ohlcv(symbol.upper(), timeframe.upper(), bars)
            if candles.empty or len(candles) <= lookahead + 30:
                return pd.DataFrame(), mt5.status_message or "Not enough candles for paper-trade simulation"

            snapshot = candles.iloc[: -lookahead]
            future = candles.iloc[-lookahead:]

            trades: list[PaperTradeResult] = []
            for strategy in create_default_strategies():
                params = dict(self.settings.get(f"strategy.{strategy.name}", {}))
                signal = strategy.generate_signal(snapshot, params)
                if signal.action == SignalAction.NO_TRADE:
                    continue
                trades.append(self.paper_trader.simulate(signal, future, symbol.upper()))

            if not trades:
                return pd.DataFrame(), "No BUY/SELL strategy signals found for simulation cycle"

            new_frame = self._paper_trade_frame_with_context(trades, timeframe.upper())
            existing = self.load_paper_trades(limit=1000)
            combined = pd.concat([existing, new_frame], ignore_index=True) if not existing.empty else new_frame
            combined = combined.tail(1000)

            self.trade_csv_path.parent.mkdir(parents=True, exist_ok=True)
            combined.to_csv(self.trade_csv_path, index=False)

            with_rows = [self._row_to_trade_result(row) for _, row in combined.iterrows()]
            self.trade_store.save_sqlite(with_rows, self.trade_sqlite_path)
            self._persist_learning_metadata(last_paper_trade_update=datetime.now(tz=timezone.utc).isoformat(timespec="seconds"))
            return TradeStore.as_dataframe(trades), f"Simulated {len(trades)} paper trades"
        finally:
            mt5.shutdown()

    def load_paper_trades(self, limit: int = 200) -> pd.DataFrame:
        frame = self._safe_read_csv(self.trade_csv_path, self._trade_columns, dataset_name="paper_trades")
        defaults = {
            "timeframe": "",
            "strategy": "",
            "result": "",
            "signal_strength": "unknown",
            "market_conditions": "unknown",
            "news_status": "unknown",
            "spread_state": "unknown",
            "session_state": "unknown",
        }
        for col, val in defaults.items():
            frame[col] = frame[col].replace("", val).fillna(val)
        return frame.tail(limit).iloc[::-1].reset_index(drop=True)

    @staticmethod
    def _row_to_trade_result(row: pd.Series) -> PaperTradeResult:
        return PaperTradeResult(
            strategy_name=str(row["strategy_name"]),
            symbol=str(row["symbol"]),
            side=str(row["side"]),
            entry=float(row["entry"]),
            exit_price=float(row["exit_price"]),
            stop_loss=float(row["stop_loss"]),
            take_profit=float(row["take_profit"]),
            open_time=pd.Timestamp(row["open_time"]).to_pydatetime(),
            close_time=pd.Timestamp(row["close_time"]).to_pydatetime(),
            outcome=str(row["outcome"]),
            pnl=float(row["pnl"]),
            is_win=bool(row["is_win"]),
        )

    def strategy_leaderboard(self, min_trades: int = 1, max_drawdown_limit: float = 999.0) -> pd.DataFrame:
        trades_frame = self.load_paper_trades(limit=2000)
        if trades_frame.empty:
            return pd.DataFrame()
        trades = [self._row_to_trade_result(row) for _, row in trades_frame.iloc[::-1].iterrows()]
        evaluator = PerformanceEvaluator(min_trades=min_trades, max_drawdown_limit=max_drawdown_limit)
        scores = evaluator.evaluate(trades)
        if not scores:
            return pd.DataFrame()
        return pd.DataFrame([asdict(score) for score in scores])

    def strategy_leaderboard_by_symbol(self, min_trades: int = 1, max_drawdown_limit: float = 999.0) -> pd.DataFrame:
        trades_frame = self.load_paper_trades(limit=5000)
        if trades_frame.empty:
            return pd.DataFrame()
        trades = [self._row_to_trade_result(row) for _, row in trades_frame.iloc[::-1].iterrows()]
        evaluator = PerformanceEvaluator(min_trades=min_trades, max_drawdown_limit=max_drawdown_limit)
        per_symbol = evaluator.leaderboard_by_symbol(trades)
        rows: list[dict[str, Any]] = []
        for symbol, scores in per_symbol.items():
            for score in scores:
                rows.append({"symbol": symbol, **asdict(score)})
        return pd.DataFrame(rows)

    def learning_center_payload(self) -> dict[str, Any]:
        datasets = load_learning_data(self.learning_dir)
        active = datasets["active"]
        candidates = datasets["candidates"]
        paper = self.load_paper_trades(limit=500)
        metadata = datasets.get("metadata", {})
        health = compute_learning_health_summary(active, candidates, paper, metadata=metadata)
        best_configs = datasets["best_config"]
        if best_configs.empty:
            best_configs = extract_best_configuration_per_symbol(active)
        return {
            **datasets,
            "health": asdict(health),
            "best_config": best_configs,
            "state_changes_prepared": prepare_state_changes(datasets["state_changes"]),
        }

    def run_historical_validation(self) -> pd.DataFrame:
        board = self.strategy_leaderboard_by_symbol(min_trades=1)
        if board.empty:
            self._append_learning_event("validation", "", "", "Historical validation skipped: no paper trades available.")
            return pd.DataFrame()
        result = board.rename(
            columns={
                "strategy_name": "strategy",
                "trades": "total_trades",
                "max_drawdown": "drawdown",
            }
        )
        result["timestamp"] = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
        save_cols = [
            "timestamp",
            "strategy",
            "symbol",
            "total_trades",
            "net_pnl",
            "win_rate",
            "drawdown",
            "profit_factor",
            "expectancy",
            "score",
        ]
        self.learning_dir.mkdir(parents=True, exist_ok=True)
        result[save_cols].to_csv(self.learning_dir / "historical_validation.csv", index=False)
        self._persist_learning_metadata(last_historical_validation_run=datetime.now(tz=timezone.utc).isoformat(timespec="seconds"))
        self._append_learning_event("validation", "", "", f"Historical validation refreshed for {len(result)} strategy-symbol rows.")
        return result[save_cols]

    def run_historical_learning(self, symbol: str, timeframe: str) -> pd.DataFrame:
        candles = self.history_pipeline.load_history(symbol, timeframe)
        if candles.empty:
            return pd.DataFrame([{"status": "no_data", "message": "No historical candles available. Fetch data first."}])

        grid_root = self.settings.get("learning.parameter_grid", {})
        symbol_grid_root = self.settings.get("learning.symbol_parameter_grid", {}).get(symbol.upper(), {})
        rows: list[dict[str, Any]] = []
        for strategy in create_default_strategies():
            defaults = dict(self.settings.get(f"strategy.{strategy.name}", {}))
            base_grid = dict(grid_root.get(strategy.name, {}))
            symbol_grid = dict(symbol_grid_root.get(strategy.name, {}))
            base_grid.update(symbol_grid)
            fixed = {k: v for k, v in defaults.items() if k not in base_grid}
            result = self.engine.optimizer.optimize(strategy, candles, base_grid, symbol.upper(), fixed)
            if result is None:
                continue
            rows.append(
                {
                    "symbol": symbol.upper(),
                    "timeframe": timeframe.upper(),
                    "strategy": result.strategy_name,
                    "historical_score": float(result.best_score),
                    "best_historical_params": json.dumps(result.best_params),
                    "report_path": result.report_path,
                    "tested_combinations": int(result.tested_combinations),
                }
            )
            self.persistence.save_best_params(symbol.upper(), timeframe.upper(), result.strategy_name, result.best_params, result.best_score)
        if not rows:
            return pd.DataFrame([{"status": "no_candidates", "message": "Historical learning found no valid candidates."}])
        out = pd.DataFrame(rows).sort_values("historical_score", ascending=False).reset_index(drop=True)
        self.persistence.save_historical_validation(out)
        self._append_learning_event(
            "historical_learning",
            "",
            symbol.upper(),
            f"Historical learning completed for {symbol.upper()}/{timeframe.upper()} ({len(out)} rows).",
        )
        return out

    def refresh_learning_data(self) -> dict[str, Any]:
        return self.learning_center_payload()

    def evaluate_open_paper_trades(self) -> tuple[int, str]:
        trades = self.load_paper_trades(limit=2000)
        if trades.empty:
            return 0, "No paper trades found."
        open_count = int((trades["outcome"].astype(str).str.upper() == "OPEN").sum())
        self._append_learning_event("paper_trades", "", "", f"Evaluated open paper trades. currently_open={open_count}.")
        return open_count, f"Open trades currently tracked: {open_count}"

    def promote_eligible_candidates(self) -> int:
        datasets = load_learning_data(self.learning_dir)
        candidates = datasets["candidates"]
        if candidates.empty:
            return 0
        eligible = candidates[candidates["promotion_eligibility"].astype(str).str.lower() == "eligible"].copy()
        if eligible.empty:
            return 0
        now = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
        active = datasets["active"].copy()
        for _, row in eligible.iterrows():
            active = pd.concat(
                [
                    active,
                    pd.DataFrame(
                        [
                            {
                                "strategy_name": row.get("strategy_name", ""),
                                "symbol": row.get("symbol", ""),
                                "timeframe": row.get("timeframe", ""),
                                "strategy_state": "promoted",
                                "historical_score": row.get("historical_score", 0),
                                "recent_score": row.get("recent_score", 0),
                                "learning_confidence": 0.7,
                                "trade_count": row.get("sample_size", 0),
                                "win_rate": 0,
                                "expectancy": 0,
                                "max_drawdown": 0,
                                "last_promoted_time": now,
                                "state_label": "promoted",
                                "parameter_summary": row.get("parameter_summary", ""),
                                "blocked_reason": "",
                                "sample_size": row.get("sample_size", 0),
                            }
                        ]
                    ),
                ],
                ignore_index=True,
            )
            self._append_state_change(now, row.get("strategy_name", ""), row.get("symbol", ""), "candidate", "promoted", "Eligibility threshold met.")
            self._append_learning_event("promotion", row.get("strategy_name", ""), row.get("symbol", ""), "Candidate promoted to active.")
        active.drop_duplicates(subset=["strategy_name", "symbol", "timeframe"], keep="last", inplace=True)
        self.learning_dir.mkdir(parents=True, exist_ok=True)
        active.to_csv(self.learning_dir / "active_strategies.csv", index=False)
        remaining = candidates[candidates["promotion_eligibility"].astype(str).str.lower() != "eligible"]
        remaining.to_csv(self.learning_dir / "candidate_strategies.csv", index=False)
        return int(len(eligible))

    def recompute_leaderboards(self) -> pd.DataFrame:
        board = self.strategy_leaderboard_by_symbol(min_trades=1)
        if board.empty:
            return board
        self.learning_dir.mkdir(parents=True, exist_ok=True)
        board.to_csv(self.learning_dir / "latest_leaderboard.csv", index=False)
        self._append_learning_event("leaderboard", "", "", f"Leaderboard recomputed ({len(board)} rows).")
        return board

    def archive_disabled_strategies(self) -> int:
        datasets = load_learning_data(self.learning_dir)
        active = datasets["active"]
        if active.empty:
            return 0
        disabled = active[active["strategy_state"].astype(str).str.lower() == "disabled"]
        if disabled.empty:
            return 0
        archive_path = self.learning_dir / "disabled_archive.csv"
        if archive_path.exists():
            existing = pd.read_csv(archive_path)
            combined = pd.concat([existing, disabled], ignore_index=True)
        else:
            combined = disabled
        combined.to_csv(archive_path, index=False)
        active = active[active["strategy_state"].astype(str).str.lower() != "disabled"]
        active.to_csv(self.learning_dir / "active_strategies.csv", index=False)
        self._append_learning_event("archive", "", "", f"Archived {len(disabled)} disabled strategy rows.")
        return int(len(disabled))

    def _build_mt5_client(self) -> MT5Client:
        return MT5Client(
            terminal_path=self.settings.get("mt5.terminal_path"),
            login=self.settings.get("mt5.login"),
            password=self.settings.get("mt5.password"),
            server=self.settings.get("mt5.server"),
            init_retries=int(self.settings.get("mt5.init_retries", 3)),
            retry_delay_seconds=float(self.settings.get("mt5.retry_delay_seconds", 0.5)),
        )

    def _paper_trade_frame_with_context(self, trades: list[PaperTradeResult], timeframe: str) -> pd.DataFrame:
        frame = TradeStore.as_dataframe(trades)
        frame["timeframe"] = timeframe
        frame["strategy"] = frame["strategy_name"]
        frame["result"] = frame["outcome"]
        frame["signal_strength"] = "unknown"
        frame["market_conditions"] = "unknown"
        frame["news_status"] = "unknown"
        frame["spread_state"] = "unknown"
        frame["session_state"] = "unknown"
        return frame

    def _persist_optimizer_snapshot(self, table: pd.DataFrame, symbol: str, timeframe: str) -> None:
        self.learning_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
        active_count = int(self.settings.get("learning.active_strategy_count", 2))
        active = table.head(active_count).copy()
        candidates = table.iloc[active_count:].copy()
        leaderboard = self.strategy_leaderboard_by_symbol(min_trades=1)

        def _score_for(strategy: str) -> tuple[float, float, float, float, float]:
            if leaderboard.empty:
                return 0.0, 0.0, 0.0, 0.0, 0.0
            row = leaderboard[(leaderboard["symbol"] == symbol) & (leaderboard["strategy_name"] == strategy)]
            if row.empty:
                return 0.0, 0.0, 0.0, 0.0, 0.0
            top = row.iloc[0]
            return float(top["trades"]), float(top["win_rate"]), float(top["expectancy"]), float(top["max_drawdown"]), float(top["score"])

        active_rows: list[dict[str, Any]] = []
        for _, row in active.iterrows():
            trades, win_rate, expectancy, drawdown, recent_score = _score_for(str(row["strategy"]))
            weighted = self.unified_scorer.score(float(row["score"]), recent_score)
            state_label = self.unified_scorer.lifecycle_state(
                sample_size=int(trades),
                recent_drawdown=float(drawdown),
                expectancy=float(expectancy),
                historical_score=float(row["score"]),
                recent_score=float(recent_score),
                previous_state="active",
            )
            active_rows.append(
                {
                    "strategy_name": row["strategy"],
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "strategy_state": state_label,
                    "historical_score": weighted.historical_score,
                    "recent_score": weighted.recent_score,
                    "combined_score": weighted.combined_score,
                    "learning_confidence": min(1.0, max(0.0, float(row["score"]) / 100)),
                    "trade_count": int(trades),
                    "win_rate": win_rate,
                    "expectancy": expectancy,
                    "max_drawdown": drawdown,
                    "last_promoted_time": now if state_label == "promoted" else "",
                    "state_label": state_label,
                    "parameter_summary": str(row["best_params"]),
                    "blocked_reason": "",
                    "sample_size": int(trades),
                }
            )
        candidate_rows: list[dict[str, Any]] = []
        for _, row in candidates.iterrows():
            trades, _win_rate, expectancy, drawdown, recent_score = _score_for(str(row["strategy"]))
            weighted = self.unified_scorer.score(float(row["score"]), recent_score)
            blocked_reason = ""
            eligibility = "eligible"
            if not self.unified_scorer.promote_allowed(sample_size=int(trades), recent_drawdown=float(drawdown), expectancy=float(expectancy)):
                eligibility = "blocked"
            if trades < self.unified_scorer.min_sample_size:
                blocked_reason = "Low sample size"
            elif expectancy < 0:
                blocked_reason = "Poor expectancy"
            elif drawdown > self.unified_scorer.max_drawdown:
                blocked_reason = "High drawdown"
            candidate_rows.append(
                {
                    "strategy_name": row["strategy"],
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "parameter_summary": str(row["best_params"]),
                    "historical_score": weighted.historical_score,
                    "recent_score": weighted.recent_score,
                    "combined_score": weighted.combined_score,
                    "promotion_eligibility": eligibility,
                    "sample_size": int(trades),
                    "blocked_reason": blocked_reason,
                }
            )

        pd.DataFrame(active_rows).to_csv(self.learning_dir / "active_strategies.csv", index=False)
        pd.DataFrame(candidate_rows).to_csv(self.learning_dir / "candidate_strategies.csv", index=False)
        best = extract_best_configuration_per_symbol(pd.DataFrame(active_rows))
        best.to_csv(self.learning_dir / "best_configurations.csv", index=False)
        self._append_learning_event("optimizer", "", symbol, f"Optimizer completed for {symbol}/{timeframe} with {len(table)} candidates.")

    def _persist_learning_metadata(self, **kwargs: Any) -> None:
        self.learning_dir.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any]
        if self.learning_metadata_path.exists():
            try:
                raw = self.learning_metadata_path.read_text(encoding="utf-8").strip()
                payload = json.loads(raw) if raw else {}
            except json.JSONDecodeError as exc:
                LOGGER.warning("Learning metadata is malformed at %s: %s. Reinitializing metadata.", self.learning_metadata_path, exc)
                payload = {}
            except Exception as exc:
                LOGGER.warning("Learning metadata could not be loaded at %s: %s. Reinitializing metadata.", self.learning_metadata_path, exc)
                payload = {}
        else:
            payload = {}
        payload.update(kwargs)
        self.learning_metadata_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _append_learning_event(self, event_type: str, strategy: str, symbol: str, message: str) -> None:
        self.learning_dir.mkdir(parents=True, exist_ok=True)
        row = pd.DataFrame(
            [
                {
                    "timestamp": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
                    "event_type": event_type,
                    "strategy": strategy,
                    "symbol": symbol,
                    "message": message,
                }
            ]
        )
        path = self.learning_dir / "learning_events.csv"
        if path.exists():
            existing = self._safe_read_csv(path, list(row.columns), dataset_name="learning_events")
            row = pd.concat([existing, row], ignore_index=True).tail(500)
        row.to_csv(path, index=False)

    def _append_state_change(
        self,
        timestamp: str,
        strategy: str,
        symbol: str,
        previous_state: str,
        new_state: str,
        reason: str,
    ) -> None:
        self.learning_dir.mkdir(parents=True, exist_ok=True)
        row = pd.DataFrame(
            [
                {
                    "timestamp": timestamp,
                    "strategy": strategy,
                    "symbol": symbol,
                    "previous_state": previous_state,
                    "new_state": new_state,
                    "reason": reason,
                    "event_type": "state_change",
                }
            ]
        )
        path = self.learning_dir / "strategy_state_changes.csv"
        if path.exists():
            existing = self._safe_read_csv(path, list(row.columns), dataset_name="strategy_state_changes")
            row = pd.concat([existing, row], ignore_index=True).tail(500)
        row.to_csv(path, index=False)

    @staticmethod
    def _empty_recommendation() -> FinalRecommendation:
        return FinalRecommendation(
            symbol="N/A",
            timeframe="N/A",
            action=SignalAction.NO_TRADE,
            market_price=0.0,
            entry=0.0,
            stop_loss=0.0,
            take_profit=0.0,
            risk_reward=0.0,
            confidence=0.0,
            selected_strategy="none",
            market_status="unknown",
            news_status="unknown",
            mt5_connection_status="unknown",
            signal_strength="weak",
            rejection_reason="",
            volatility_state="unknown",
            next_news_event=None,
            reasons=[],
            timestamp=datetime.utcnow(),
        )
