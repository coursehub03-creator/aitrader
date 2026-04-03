"""Service layer for Streamlit dashboard integration."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import pandas as pd

from app.main import build_engine
from config_loader import Settings, load_settings
from core.mt5_client import MT5Client
from core.paper_trading import PaperTrader, TradeStore
from core.types import FinalRecommendation, PaperTradeResult, SignalAction
from learning.evaluator import PerformanceEvaluator
from monitoring.alerts import AlertPolicy, AlertCooldownStore
from notification.telegram_notifier import TelegramConfig, TelegramNotifier
from strategy.registry import create_default_strategies


class DashboardService:
    """Thin adapter that reuses backend modules for UI flows."""

    def __init__(self, settings_path: str = "config/settings.yaml") -> None:
        self.settings_path = settings_path
        self.settings: Settings = load_settings(settings_path)
        self.engine = build_engine(self.settings)
        self.paper_trader = PaperTrader()
        self.trade_store = TradeStore()
        self.recent_recommendations_path = Path("logs/ui_recent_recommendations.csv")
        self.alert_history_path = Path("logs/ui_alert_history.csv")
        self.alert_state_path = Path("logs/ui_alert_state.json")
        self.trade_csv_path = Path("logs/paper_trades.csv")
        self.trade_sqlite_path = Path("logs/paper_trades.sqlite3")

    def refresh_settings(self) -> None:
        self.settings = load_settings(self.settings_path)
        self.engine = build_engine(self.settings)

    def evaluate_and_send_alert(self, recommendation: FinalRecommendation) -> tuple[str, str]:
        policy = AlertPolicy(
            min_confidence=float(self.settings.get("recommendation.min_confidence", 0.6)),
            min_risk_reward=float(self.settings.get("recommendation.min_risk_reward", 1.5)),
        )
        qualifies, qualify_reason = policy.qualifies(recommendation)
        if not qualifies:
            return "suppressed", qualify_reason

        cooldown = AlertCooldownStore(
            self.alert_state_path,
            cooldown_seconds=int(self.settings.get("monitoring.alert_cooldown_seconds", 900)),
        )
        key = cooldown.build_key(recommendation)
        can_send, cooldown_reason = cooldown.can_send(key, datetime.now(tz=timezone.utc))
        if not can_send:
            return "suppressed", cooldown_reason

        notifier = TelegramNotifier(
            TelegramConfig(
                enabled=bool(self.settings.get("monitoring.telegram.enabled", False)),
                bot_token=str(self.settings.get("monitoring.telegram.bot_token", "")),
                chat_id=str(self.settings.get("monitoring.telegram.chat_id", "")),
                timeout_seconds=float(self.settings.get("monitoring.telegram.timeout_seconds", 10)),
            )
        )
        sent, send_reason = notifier.send_recommendation_alert(recommendation)
        if sent:
            cooldown.mark_sent(key, datetime.now(tz=timezone.utc))
            return "sent", send_reason
        return "failed", send_reason

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
            "next_news_event": json.dumps(recommendation.next_news_event or {}),
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
            existing = pd.read_csv(self.recent_recommendations_path)
            combined = pd.concat([existing, row], ignore_index=True)
        else:
            combined = row

        combined = combined.tail(500)
        combined.to_csv(self.recent_recommendations_path, index=False)

    def persist_alert_event(self, recommendation: FinalRecommendation, status: str, reason: str) -> None:
        row = pd.DataFrame(
            [
                {
                    "timestamp": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
                    "symbol": recommendation.symbol,
                    "action": recommendation.action.value if hasattr(recommendation.action, "value") else recommendation.action,
                    "signal_strength": recommendation.signal_strength,
                    "confidence": recommendation.confidence,
                    "risk_reward": recommendation.risk_reward,
                    "status": status,
                    "reason": reason,
                }
            ]
        )
        self.alert_history_path.parent.mkdir(parents=True, exist_ok=True)
        if self.alert_history_path.exists():
            existing = pd.read_csv(self.alert_history_path)
            combined = pd.concat([existing, row], ignore_index=True)
        else:
            combined = row
        combined.tail(500).to_csv(self.alert_history_path, index=False)

    def recent_alert_events(self, limit: int = 50) -> pd.DataFrame:
        if not self.alert_history_path.exists():
            return pd.DataFrame()
        frame = pd.read_csv(self.alert_history_path)
        return frame.tail(limit).iloc[::-1].reset_index(drop=True)

    def recent_recommendations(self, limit: int = 50) -> pd.DataFrame:
        if not self.recent_recommendations_path.exists():
            return pd.DataFrame()
        frame = pd.read_csv(self.recent_recommendations_path)
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
            return pd.DataFrame(rows).sort_values("score", ascending=False)
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

            existing = self.load_paper_trades(limit=1000)
            combined = pd.concat([existing, TradeStore.as_dataframe(trades)], ignore_index=True) if not existing.empty else TradeStore.as_dataframe(trades)
            combined = combined.tail(1000)

            self.trade_csv_path.parent.mkdir(parents=True, exist_ok=True)
            combined.to_csv(self.trade_csv_path, index=False)

            with_rows = [self._row_to_trade_result(row) for _, row in combined.iterrows()]
            self.trade_store.save_sqlite(with_rows, self.trade_sqlite_path)
            return TradeStore.as_dataframe(trades), f"Simulated {len(trades)} paper trades"
        finally:
            mt5.shutdown()

    def load_paper_trades(self, limit: int = 200) -> pd.DataFrame:
        if not self.trade_csv_path.exists():
            return pd.DataFrame(columns=TradeStore.REQUIRED_COLUMNS)
        frame = pd.read_csv(self.trade_csv_path)
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

    def _build_mt5_client(self) -> MT5Client:
        return MT5Client(
            terminal_path=self.settings.get("mt5.terminal_path"),
            login=self.settings.get("mt5.login"),
            password=self.settings.get("mt5.password"),
            server=self.settings.get("mt5.server"),
            init_retries=int(self.settings.get("mt5.init_retries", 3)),
            retry_delay_seconds=float(self.settings.get("mt5.retry_delay_seconds", 0.5)),
        )
