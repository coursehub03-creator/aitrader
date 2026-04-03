"""Self-optimization layer with robust parameter search and reporting."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import product
import json
from pathlib import Path
import random
from typing import Any

import pandas as pd

from core.paper_trading import PaperTrader
from core.types import PaperTradeResult, SignalAction
from learning.evaluator import PerformanceEvaluator
from strategy.base import TradingStrategy


@dataclass(slots=True)
class SplitPerformance:
    score: float
    trades: int
    net_pnl: float
    max_drawdown: float
    win_rate: float


@dataclass(slots=True)
class ParameterSetScore:
    params: dict[str, Any]
    train: SplitPerformance
    validation: SplitPerformance
    forward: SplitPerformance
    overfit_penalty: float
    robustness_score: float
    rationale: str


@dataclass(slots=True)
class OptimizationResult:
    strategy_name: str
    best_params: dict[str, Any]
    best_score: float
    tested_combinations: int
    selected_candidates: list[ParameterSetScore]
    report_path: str
    best_expectancy: float = 0.0


class ParameterOptimizer:
    def __init__(
        self,
        lookahead_bars: int = 8,
        min_history_bars: int = 120,
        step: int = 10,
        search_method: str = "grid",
        random_search_trials: int = 20,
        min_validation_trades: int = 2,
        min_forward_trades: int = 2,
        report_dir: str | Path = "logs/optimization",
    ) -> None:
        self.lookahead_bars = lookahead_bars
        self.min_history_bars = min_history_bars
        self.step = step
        self.search_method = search_method
        self.random_search_trials = random_search_trials
        self.min_validation_trades = min_validation_trades
        self.min_forward_trades = min_forward_trades
        self.paper_trader = PaperTrader()
        self.evaluator = PerformanceEvaluator(min_trades=1, max_drawdown_limit=float("inf"))
        self.report_dir = Path(report_dir)
        self.report_dir.mkdir(parents=True, exist_ok=True)

    def optimize(
        self,
        strategy: TradingStrategy,
        candles: pd.DataFrame,
        parameter_grid: dict[str, list[Any]],
        symbol: str,
        fixed_params: dict[str, Any] | None = None,
        keep_top_n: int = 3,
    ) -> OptimizationResult | None:
        if candles.empty or len(candles) < self.min_history_bars:
            return None

        fixed = fixed_params or {}
        combos = self._parameter_combinations(parameter_grid) or [dict()]
        train, validation, forward = self._split_candles(candles)

        ranked: list[ParameterSetScore] = []
        for combo in combos:
            params = {**fixed, **combo}
            train_perf = self._evaluate_split(strategy, train, params, symbol)
            validation_perf = self._evaluate_split(strategy, validation, params, symbol)
            forward_perf = self._evaluate_split(strategy, forward, params, symbol)

            if validation_perf.trades < self.min_validation_trades or forward_perf.trades < self.min_forward_trades:
                continue

            overfit_penalty = abs(train_perf.score - validation_perf.score) * 0.25
            robustness_score = (
                validation_perf.score * 0.55
                + forward_perf.score * 0.35
                + train_perf.score * 0.10
                - overfit_penalty
            )
            rationale = (
                "Selected for strong validation/forward performance with controlled overfit gap; "
                f"val_trades={validation_perf.trades}, forward_trades={forward_perf.trades}, "
                f"overfit_penalty={overfit_penalty:.2f}"
            )
            ranked.append(
                ParameterSetScore(
                    params=params,
                    train=train_perf,
                    validation=validation_perf,
                    forward=forward_perf,
                    overfit_penalty=overfit_penalty,
                    robustness_score=robustness_score,
                    rationale=rationale,
                )
            )

        if not ranked:
            return None

        ranked.sort(key=lambda item: item.robustness_score, reverse=True)
        top_n = max(1, min(keep_top_n, len(ranked)))
        selected_candidates = ranked[:top_n]
        best = selected_candidates[0]
        report_path = self._save_report(strategy.name, symbol, selected_candidates, len(combos))
        self._update_symbol_best_registry(strategy.name, symbol, best.params, best.robustness_score)

        return OptimizationResult(
            strategy_name=strategy.name,
            best_params=best.params,
            best_score=best.robustness_score,
            best_expectancy=(best.forward.net_pnl / best.forward.trades) if best.forward.trades else 0.0,
            tested_combinations=len(combos),
            selected_candidates=selected_candidates,
            report_path=str(report_path),
        )

    def _update_symbol_best_registry(
        self,
        strategy_name: str,
        symbol: str,
        best_params: dict[str, Any],
        best_score: float,
    ) -> None:
        registry_path = self.report_dir / "best_params_by_symbol.json"
        if registry_path.exists():
            payload = json.loads(registry_path.read_text(encoding="utf-8"))
        else:
            payload = {}
        payload.setdefault(symbol, {})
        payload[symbol][strategy_name] = {"best_params": best_params, "best_score": float(best_score)}
        registry_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self._write_symbol_leaderboard(payload)

    def _write_symbol_leaderboard(self, registry: dict[str, Any]) -> None:
        rows: list[dict[str, Any]] = []
        for symbol, by_strategy in registry.items():
            if not isinstance(by_strategy, dict):
                continue
            for strategy_name, details in by_strategy.items():
                if not isinstance(details, dict):
                    continue
                rows.append(
                    {
                        "symbol": str(symbol).upper(),
                        "strategy_name": str(strategy_name),
                        "best_score": float(details.get("best_score", 0.0)),
                        "best_params": details.get("best_params", {}),
                    }
                )
        leaderboard = sorted(rows, key=lambda item: (item["symbol"], -item["best_score"], item["strategy_name"]))
        for idx, row in enumerate(leaderboard):
            previous_symbol = leaderboard[idx - 1]["symbol"] if idx > 0 else None
            if row["symbol"] != previous_symbol:
                rank = 1
            else:
                rank = int(leaderboard[idx - 1]["symbol_rank"]) + 1
            row["symbol_rank"] = rank

        (self.report_dir / "symbol_optimizer_leaderboard.json").write_text(
            json.dumps(leaderboard, indent=2),
            encoding="utf-8",
        )

    def _evaluate_split(
        self,
        strategy: TradingStrategy,
        candles: pd.DataFrame,
        params: dict[str, Any],
        symbol: str,
    ) -> SplitPerformance:
        results = self._backtest(strategy, candles, params, symbol)
        if not results:
            return SplitPerformance(score=float("-inf"), trades=0, net_pnl=0.0, max_drawdown=0.0, win_rate=0.0)

        evaluated = self.evaluator.evaluate(results)
        if not evaluated:
            return SplitPerformance(score=float("-inf"), trades=len(results), net_pnl=0.0, max_drawdown=0.0, win_rate=0.0)

        top = evaluated[0]
        return SplitPerformance(
            score=top.score,
            trades=top.trades,
            net_pnl=top.net_pnl,
            max_drawdown=top.max_drawdown,
            win_rate=top.win_rate,
        )

    def _split_candles(self, candles: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        total = len(candles)
        train_end = max(self.min_history_bars, int(total * 0.60))
        validation_end = min(total - 1, train_end + max(self.min_history_bars // 3, int(total * 0.20)))

        train = candles.iloc[:train_end].copy()
        validation = candles.iloc[:validation_end].copy()
        forward = candles.copy()
        return train, validation, forward

    def _backtest(
        self,
        strategy: TradingStrategy,
        candles: pd.DataFrame,
        params: dict[str, Any],
        symbol: str,
    ) -> list[PaperTradeResult]:
        results: list[PaperTradeResult] = []
        end = len(candles) - self.lookahead_bars
        warmup = max(30, min(self.min_history_bars, max(30, len(candles) // 2)))
        for i in range(warmup, end, self.step):
            snapshot = candles.iloc[: i + 1]
            signal = strategy.generate_signal(snapshot, params)
            if signal.action == SignalAction.NO_TRADE:
                continue
            future = candles.iloc[i + 1 : i + 1 + self.lookahead_bars]
            if future.empty:
                continue
            results.append(self.paper_trader.simulate(signal, future, symbol))
        return results

    def _parameter_combinations(self, parameter_grid: dict[str, list[Any]]) -> list[dict[str, Any]]:
        all_combinations = self._grid(parameter_grid)
        if self.search_method != "randomized" or len(all_combinations) <= self.random_search_trials:
            return all_combinations
        return random.sample(all_combinations, k=self.random_search_trials)

    @staticmethod
    def _grid(parameter_grid: dict[str, list[Any]]) -> list[dict[str, Any]]:
        if not parameter_grid:
            return []
        keys = list(parameter_grid.keys())
        values = [parameter_grid[key] for key in keys]
        return [dict(zip(keys, combo)) for combo in product(*values)]

    def _save_report(
        self,
        strategy_name: str,
        symbol: str,
        candidates: list[ParameterSetScore],
        tested_combinations: int,
    ) -> Path:
        safe_symbol = symbol.replace("/", "_")
        report_path = self.report_dir / f"{strategy_name}_{safe_symbol}_optimization_report.json"
        payload = {
            "strategy": strategy_name,
            "symbol": symbol,
            "tested_combinations": tested_combinations,
            "selection_policy": {
                "objective": "maximize robustness_score",
                "weights": {
                    "validation": 0.55,
                    "forward": 0.35,
                    "training": 0.10,
                    "overfit_penalty": 0.25,
                },
                "min_validation_trades": self.min_validation_trades,
                "min_forward_trades": self.min_forward_trades,
            },
            "winning_parameter_sets": [asdict(candidate) for candidate in candidates],
        }
        report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return report_path
