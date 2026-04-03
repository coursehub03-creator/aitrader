"""Paper-trade simulator only (no live execution)."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from core.types import PaperTradeResult, SignalAction, StrategySignal


class PaperTrader:
    def simulate(self, signal: StrategySignal, future_df: pd.DataFrame, symbol: str) -> PaperTradeResult:
        exit_price = signal.entry
        is_win = False

        for _, row in future_df.iterrows():
            high = float(row["high"])
            low = float(row["low"])
            if signal.action == SignalAction.BUY:
                if low <= signal.stop_loss:
                    exit_price = signal.stop_loss
                    break
                if high >= signal.take_profit:
                    exit_price = signal.take_profit
                    is_win = True
                    break
            elif signal.action == SignalAction.SELL:
                if high >= signal.stop_loss:
                    exit_price = signal.stop_loss
                    break
                if low <= signal.take_profit:
                    exit_price = signal.take_profit
                    is_win = True
                    break

        if signal.action not in {SignalAction.BUY, SignalAction.SELL}:
            raise ValueError(f"PaperTrader expects BUY/SELL signal, got {signal.action}")

        pnl = exit_price - signal.entry if signal.action == SignalAction.BUY else signal.entry - exit_price
        return PaperTradeResult(
            strategy_name=signal.strategy_name,
            symbol=symbol,
            action=signal.action,
            entry=signal.entry,
            exit_price=exit_price,
            pnl=float(pnl),
            is_win=is_win,
            timestamp=datetime.utcnow(),
        )
