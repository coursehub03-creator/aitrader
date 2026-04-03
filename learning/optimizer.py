"""Simple grid-search optimizer for strategy parameters."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Any

import pandas as pd

from core.paper_trading import PaperTrader
from core.types import PaperTradeResult
from learning.evaluator import PerformanceEvaluator
from strategy.base import TradingStrategy


@dataclass(slots=True)
class OptimizationResult:
    strategy_name: str
    best_params: dict[str, Any]
    best_score: float
    tested_combinations: int


class ParameterOptimizer:
    def __init__(self, lookahead_bars: int = 8, min_history_bars: int = 120, step: int = 10) -> None:
        self.lookahead_bars = lookahead_bars
        self.min_history_bars = min_history_bars
        self.step = step
        self.paper_trader = PaperTrader()
        self.evaluator = PerformanceEvaluator()

    def optimize(
        self,
        strategy: TradingStrategy,
        candles: pd.DataFrame,
        parameter_grid: dict[str, list[Any]],
        symbol: str,
        fixed_params: dict[str, Any] | None = None,
    ) -> OptimizationResult | None:
        if candles.empty or len(candles) < self.min_history_bars:
            return None

        fixed = fixed_params or {}
        combos = self._grid(parameter_grid) or [dict()]
        best_score = float("-inf")
        best_params: dict[str, Any] = dict(fixed)

        for combo in combos:
            params = {**fixed, **combo}
            results = self._backtest(strategy, candles, params, symbol)
            if not results:
                continue
            score = self.evaluator.evaluate(results)[0].score
            if score > best_score:
                best_score = score
                best_params = params

        if best_score == float("-inf"):
            return None

        return OptimizationResult(strategy.name, best_params, best_score, len(combos))

    def _backtest(
        self,
        strategy: TradingStrategy,
        candles: pd.DataFrame,
        params: dict[str, Any],
        symbol: str,
    ) -> list[PaperTradeResult]:
        results: list[PaperTradeResult] = []
        end = len(candles) - self.lookahead_bars
        for i in range(self.min_history_bars, end, self.step):
            snapshot = candles.iloc[: i + 1]
            signal = strategy.generate_signal(snapshot, params)
            if signal is None:
                continue
            future = candles.iloc[i + 1 : i + 1 + self.lookahead_bars]
            if future.empty:
                continue
            results.append(self.paper_trader.simulate(signal, future, symbol))
        return results

    @staticmethod
    def _grid(parameter_grid: dict[str, list[Any]]) -> list[dict[str, Any]]:
        if not parameter_grid:
            return []
        keys = list(parameter_grid.keys())
        values = [parameter_grid[key] for key in keys]
        return [dict(zip(keys, combo)) for combo in product(*values)]
