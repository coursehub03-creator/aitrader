"""Evaluate strategy paper-trade outcomes."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from core.types import PaperTradeResult, StrategyScore


class PerformanceEvaluator:
    def __init__(self, min_trades: int = 5, max_drawdown_limit: float = 5.0) -> None:
        self.min_trades = min_trades
        self.max_drawdown_limit = max_drawdown_limit

    def evaluate(self, results: list[PaperTradeResult]) -> list[StrategyScore]:
        return self.leaderboard(results)

    def leaderboard(self, results: list[PaperTradeResult]) -> list[StrategyScore]:
        grouped: dict[str, list[PaperTradeResult]] = defaultdict(list)
        for result in results:
            grouped[result.strategy_name].append(result)

        scores: list[StrategyScore] = []
        for strategy_name, trades in grouped.items():
            pnl = np.array([t.pnl for t in trades], dtype=float)
            equity = pnl.cumsum()
            running_max = np.maximum.accumulate(np.insert(equity, 0, 0.0))[1:]
            drawdown = running_max - equity

            total_profit = float(pnl.sum())
            max_drawdown = float(drawdown.max()) if len(drawdown) else 0.0
            win_rate = float((pnl > 0).mean()) if len(pnl) else 0.0
            loss_rate = float((pnl < 0).mean()) if len(pnl) else 0.0
            avg_pnl = float(pnl.mean()) if len(pnl) else 0.0
            wins = pnl[pnl > 0].sum()
            losses = abs(float(pnl[pnl < 0].sum()))
            profit_factor = float(wins / losses) if losses > 0 else (float("inf") if wins > 0 else 0.0)
            expectancy = avg_pnl

            if len(trades) < self.min_trades or max_drawdown > self.max_drawdown_limit:
                continue

            # Balanced scoring: reward return quality and consistency while penalizing risk.
            score = (
                total_profit * 0.25
                + avg_pnl * 0.20
                + win_rate * 100 * 0.15
                + max(0.0, 100 - (max_drawdown * 10)) * 0.20
                + min(profit_factor, 5.0) * 10 * 0.20
            )
            scores.append(
                StrategyScore(
                    strategy_name=strategy_name,
                    score=float(score),
                    net_pnl=total_profit,
                    trades=len(trades),
                    max_drawdown=max_drawdown,
                    win_rate=win_rate,
                    loss_rate=loss_rate,
                    average_pnl=avg_pnl,
                    profit_factor=profit_factor,
                    expectancy=expectancy,
                )
            )

        return sorted(scores, key=lambda item: item.score, reverse=True)

    def leaderboard_by_symbol(self, results: list[PaperTradeResult]) -> dict[str, list[StrategyScore]]:
        grouped: dict[str, list[PaperTradeResult]] = defaultdict(list)
        for result in results:
            grouped[result.symbol].append(result)
        return {symbol: self.leaderboard(items) for symbol, items in grouped.items()}

    @staticmethod
    def save_leaderboard_csv(scores: list[StrategyScore], output_path: str | Path) -> None:
        frame = pd.DataFrame(
            [
                {
                    "strategy_name": score.strategy_name,
                    "score": score.score,
                    "total_trades": score.trades,
                    "win_rate": score.win_rate,
                    "loss_rate": score.loss_rate,
                    "net_pnl": score.net_pnl,
                    "average_pnl": score.average_pnl,
                    "max_drawdown": score.max_drawdown,
                    "profit_factor": score.profit_factor,
                    "expectancy": score.expectancy,
                }
                for score in scores
            ]
        )
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, index=False)

    @staticmethod
    def save_leaderboard_sqlite(
        scores: list[StrategyScore],
        database_path: str | Path,
        table_name: str = "strategy_leaderboard",
    ) -> None:
        frame = pd.DataFrame(
            [
                {
                    "strategy_name": score.strategy_name,
                    "score": score.score,
                    "total_trades": score.trades,
                    "win_rate": score.win_rate,
                    "loss_rate": score.loss_rate,
                    "net_pnl": score.net_pnl,
                    "average_pnl": score.average_pnl,
                    "max_drawdown": score.max_drawdown,
                    "profit_factor": score.profit_factor,
                    "expectancy": score.expectancy,
                }
                for score in scores
            ]
        )
        path = Path(database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as conn:
            frame.to_sql(table_name, conn, if_exists="replace", index=False)
