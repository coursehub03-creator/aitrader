"""Paper-trade simulator only (no live execution)."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from core.types import PaperTradeResult, SignalAction, StrategySignal


class PaperTrader:
    @staticmethod
    def _extract_time(row: pd.Series, default: datetime) -> datetime:
        value: Any = row.get("time")
        if value is None:
            return default
        stamp = pd.Timestamp(value)
        return stamp.to_pydatetime()

    def simulate(self, signal: StrategySignal, future_df: pd.DataFrame, symbol: str) -> PaperTradeResult:
        if signal.action not in {SignalAction.BUY, SignalAction.SELL}:
            raise ValueError(f"PaperTrader expects BUY/SELL signal, got {signal.action}")
        if future_df.empty:
            raise ValueError("future_df must include at least one bar for paper-trade simulation")

        utc_now = datetime.utcnow()
        first_row = future_df.iloc[0]
        open_time = self._extract_time(first_row, utc_now)
        exit_price = signal.entry
        close_time = open_time
        outcome = "OPEN"
        is_win = False

        for _, row in future_df.iterrows():
            high = float(row["high"])
            low = float(row["low"])
            close_time = self._extract_time(row, close_time)
            if signal.action == SignalAction.BUY:
                if low <= signal.stop_loss:
                    exit_price = signal.stop_loss
                    outcome = "LOSS"
                    break
                if high >= signal.take_profit:
                    exit_price = signal.take_profit
                    is_win = True
                    outcome = "WIN"
                    break
            elif signal.action == SignalAction.SELL:
                if high >= signal.stop_loss:
                    exit_price = signal.stop_loss
                    outcome = "LOSS"
                    break
                if low <= signal.take_profit:
                    exit_price = signal.take_profit
                    is_win = True
                    outcome = "WIN"
                    break

        if outcome == "OPEN":
            outcome = "BREAKEVEN"

        pnl = exit_price - signal.entry if signal.action == SignalAction.BUY else signal.entry - exit_price
        return PaperTradeResult(
            strategy_name=signal.strategy_name,
            symbol=symbol,
            side=signal.action,
            entry=signal.entry,
            exit_price=exit_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            open_time=open_time,
            close_time=close_time,
            outcome=outcome,
            pnl=float(pnl),
            is_win=is_win,
        )


class TradeStore:
    """Structured persistence for paper trades."""

    REQUIRED_COLUMNS = (
        "strategy_name",
        "symbol",
        "side",
        "entry",
        "exit_price",
        "stop_loss",
        "take_profit",
        "open_time",
        "close_time",
        "outcome",
        "pnl",
        "is_win",
    )

    @classmethod
    def as_dataframe(cls, trades: list[PaperTradeResult]) -> pd.DataFrame:
        rows = [
            {
                "strategy_name": trade.strategy_name,
                "symbol": trade.symbol,
                "side": trade.side,
                "entry": trade.entry,
                "exit_price": trade.exit_price,
                "stop_loss": trade.stop_loss,
                "take_profit": trade.take_profit,
                "open_time": trade.open_time.isoformat(),
                "close_time": trade.close_time.isoformat(),
                "outcome": trade.outcome,
                "pnl": trade.pnl,
                "is_win": trade.is_win,
            }
            for trade in trades
        ]
        return pd.DataFrame(rows, columns=cls.REQUIRED_COLUMNS)

    @classmethod
    def save_csv(cls, trades: list[PaperTradeResult], output_path: str | Path) -> None:
        frame = cls.as_dataframe(trades)
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, index=False)

    @classmethod
    def save_sqlite(
        cls,
        trades: list[PaperTradeResult],
        database_path: str | Path,
        table_name: str = "paper_trades",
    ) -> None:
        frame = cls.as_dataframe(trades)
        path = Path(database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as conn:
            frame.to_sql(table_name, conn, if_exists="replace", index=False)
