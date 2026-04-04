"""Historical strategy validation pipeline over stored candle history."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

import numpy as np
import pandas as pd

from core.paper_trading import PaperTrader
from core.types import PaperTradeResult, SignalAction
from learning.optimizer import ParameterOptimizer
from strategy.base import TradingStrategy


@dataclass(slots=True)
class ValidationMetrics:
    total_trades: int
    win_rate: float
    loss_rate: float
    net_pnl: float
    max_drawdown: float
    profit_factor: float
    expectancy: float
    avg_reward_risk: float
    score: float


class HistoricalValidationPipeline:
    """Explainable historical validation with rolling train/validation windows."""

    def __init__(
        self,
        lookahead_bars: int = 8,
        step: int = 10,
        min_train_bars: int = 120,
        validation_bars: int = 60,
        rolling_step: int = 30,
    ) -> None:
        self.lookahead_bars = lookahead_bars
        self.step = step
        self.min_train_bars = min_train_bars
        self.validation_bars = validation_bars
        self.rolling_step = rolling_step
        self.paper_trader = PaperTrader()

    def evaluate_strategy(
        self,
        *,
        symbol: str,
        timeframe: str,
        strategy: TradingStrategy,
        candles: pd.DataFrame,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        windows = self._rolling_windows(candles)
        if not windows:
            return {}

        train_trades: list[PaperTradeResult] = []
        validation_trades: list[PaperTradeResult] = []
        for train_slice, validation_slice in windows:
            train_trades.extend(self._backtest(strategy, train_slice, params, symbol))
            validation_trades.extend(self._backtest(strategy, validation_slice, params, symbol))

        train_metrics = self._metrics(train_trades)
        validation_metrics = self._metrics(validation_trades)
        if validation_metrics.total_trades == 0:
            return {}

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "strategy": strategy.name,
            "params": params,
            "train_windows": len(windows),
            "train_total_trades": train_metrics.total_trades,
            "train_win_rate": train_metrics.win_rate,
            "train_loss_rate": train_metrics.loss_rate,
            "train_net_pnl": train_metrics.net_pnl,
            "train_max_drawdown": train_metrics.max_drawdown,
            "train_profit_factor": train_metrics.profit_factor,
            "train_expectancy": train_metrics.expectancy,
            "train_avg_reward_risk": train_metrics.avg_reward_risk,
            "train_score": train_metrics.score,
            "total_trades": validation_metrics.total_trades,
            "win_rate": validation_metrics.win_rate,
            "loss_rate": validation_metrics.loss_rate,
            "net_pnl": validation_metrics.net_pnl,
            "max_drawdown": validation_metrics.max_drawdown,
            "profit_factor": validation_metrics.profit_factor,
            "expectancy": validation_metrics.expectancy,
            "avg_reward_risk": validation_metrics.avg_reward_risk,
            "score": validation_metrics.score,
            "final_validation_score": validation_metrics.score,
            "explainability": (
                "Rolling validation score = 0.25*net_pnl + 0.25*expectancy + "
                "0.20*(win_rate*100) + 0.10*profit_factor*10 + 0.10*avg_reward_risk*10 + 0.10*risk_penalty"
            ),
        }

    def choose_params(
        self,
        *,
        optimizer: ParameterOptimizer,
        strategy: TradingStrategy,
        candles: pd.DataFrame,
        symbol: str,
        timeframe: str,
        fixed_params: dict[str, Any],
        parameter_grid: dict[str, list[Any]],
    ) -> dict[str, Any]:
        if not parameter_grid:
            return fixed_params
        result = optimizer.optimize(strategy, candles, parameter_grid, symbol, timeframe, fixed_params=fixed_params)
        if result is None:
            return fixed_params
        return result.best_params

    def _rolling_windows(self, candles: pd.DataFrame) -> list[tuple[pd.DataFrame, pd.DataFrame]]:
        total = len(candles)
        windows: list[tuple[pd.DataFrame, pd.DataFrame]] = []
        start = 0
        while (start + self.min_train_bars + self.validation_bars) <= total:
            train_end = start + self.min_train_bars
            val_end = train_end + self.validation_bars
            train = candles.iloc[start:train_end].copy()
            validation = candles.iloc[train_end:val_end].copy()
            windows.append((train, validation))
            start += self.rolling_step
        return windows

    def _backtest(
        self,
        strategy: TradingStrategy,
        candles: pd.DataFrame,
        params: dict[str, Any],
        symbol: str,
    ) -> list[PaperTradeResult]:
        trades: list[PaperTradeResult] = []
        end = len(candles) - self.lookahead_bars
        warmup = max(30, min(120, max(30, len(candles) // 2)))
        for i in range(warmup, end, self.step):
            snapshot = candles.iloc[: i + 1]
            signal = strategy.generate_signal(snapshot, params)
            if signal.action == SignalAction.NO_TRADE:
                continue
            future = candles.iloc[i + 1 : i + 1 + self.lookahead_bars]
            if future.empty:
                continue
            trades.append(self.paper_trader.simulate(signal, future, symbol))
        return trades

    @staticmethod
    def _metrics(trades: list[PaperTradeResult]) -> ValidationMetrics:
        if not trades:
            return ValidationMetrics(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

        pnl = np.array([t.pnl for t in trades], dtype=float)
        equity = pnl.cumsum()
        running_max = np.maximum.accumulate(np.insert(equity, 0, 0.0))[1:]
        drawdown = running_max - equity

        total_trades = int(len(trades))
        net_pnl = float(pnl.sum())
        win_rate = float((pnl > 0).mean())
        loss_rate = float((pnl < 0).mean())
        expectancy = float(pnl.mean())
        max_drawdown = float(drawdown.max()) if len(drawdown) else 0.0
        wins = float(pnl[pnl > 0].sum())
        losses = abs(float(pnl[pnl < 0].sum()))
        profit_factor = float(wins / losses) if losses > 0 else (float("inf") if wins > 0 else 0.0)

        reward_risk_values: list[float] = []
        for trade in trades:
            risk = abs(float(trade.entry) - float(trade.stop_loss))
            reward = abs(float(trade.take_profit) - float(trade.entry))
            if risk > 0:
                reward_risk_values.append(reward / risk)
        avg_reward_risk = float(np.mean(reward_risk_values)) if reward_risk_values else 0.0

        risk_penalty = max(0.0, 100.0 - (max_drawdown * 10.0))
        score = (
            (net_pnl * 0.25)
            + (expectancy * 0.25)
            + ((win_rate * 100.0) * 0.20)
            + (min(profit_factor, 5.0) * 10.0 * 0.10)
            + (min(avg_reward_risk, 5.0) * 10.0 * 0.10)
            + (risk_penalty * 0.10)
        )

        return ValidationMetrics(
            total_trades=total_trades,
            win_rate=win_rate,
            loss_rate=loss_rate,
            net_pnl=net_pnl,
            max_drawdown=max_drawdown,
            profit_factor=profit_factor,
            expectancy=expectancy,
            avg_reward_risk=avg_reward_risk,
            score=float(score),
        )


def format_historical_results(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    frame["params"] = frame["params"].apply(lambda value: json.dumps(value, sort_keys=True))
    frame["rank"] = frame.groupby(["symbol", "timeframe"])["score"].rank(method="dense", ascending=False).astype(int)
    return frame.sort_values(["symbol", "timeframe", "rank", "score"], ascending=[True, True, True, False]).reset_index(drop=True)
