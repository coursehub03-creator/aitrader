"""Evaluate strategy paper-trade outcomes."""

from __future__ import annotations

from collections import defaultdict

import numpy as np

from core.types import PaperTradeResult, StrategyScore


class PerformanceEvaluator:
    def evaluate(self, results: list[PaperTradeResult]) -> list[StrategyScore]:
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
            wins = pnl[pnl > 0].sum()
            losses = abs(float(pnl[pnl < 0].sum()))
            profit_factor = float(wins / losses) if losses > 0 else float(wins)

            score = (
                total_profit * 0.35
                + len(trades) * 0.05
                + win_rate * 100 * 0.25
                + profit_factor * 10 * 0.25
                - max_drawdown * 0.3
            )
            scores.append(
                StrategyScore(
                    strategy_name=strategy_name,
                    score=float(score),
                    profit=total_profit,
                    trades=len(trades),
                    max_drawdown=max_drawdown,
                    win_rate=win_rate,
                    profit_factor=profit_factor,
                )
            )

        return sorted(scores, key=lambda item: item.score, reverse=True)
