from datetime import datetime, timedelta

import pandas as pd

from core.paper_trading import PaperTrader, TradeStore
from core.types import SignalAction, StrategySignal


def test_paper_trader_simulates_open_and_close() -> None:
    now = datetime.utcnow()
    signal = StrategySignal(
        strategy_name="trend_rsi",
        action=SignalAction.BUY,
        entry=1.1000,
        stop_loss=1.0900,
        take_profit=1.1200,
        confidence=0.8,
        reasons=["test"],
    )
    future = pd.DataFrame(
        {
            "time": [now, now + timedelta(minutes=15)],
            "high": [1.1050, 1.1210],
            "low": [1.0990, 1.1010],
        }
    )

    trade = PaperTrader().simulate(signal, future, "EURUSD")
    assert trade.symbol == "EURUSD"
    assert trade.side == SignalAction.BUY
    assert trade.outcome == "WIN"
    assert trade.exit_price == signal.take_profit
    assert trade.open_time == now
    assert trade.close_time == now + timedelta(minutes=15)


def test_trade_store_saves_csv_and_sqlite(tmp_path) -> None:
    now = datetime.utcnow()
    signal = StrategySignal(
        strategy_name="breakout_atr",
        action=SignalAction.SELL,
        entry=1.2000,
        stop_loss=1.2100,
        take_profit=1.1800,
        confidence=0.7,
        reasons=["test"],
    )
    future = pd.DataFrame({"time": [now], "high": [1.2050], "low": [1.1790]})
    trade = PaperTrader().simulate(signal, future, "GBPUSD")

    csv_path = tmp_path / "paper_trades.csv"
    db_path = tmp_path / "paper_trades.db"

    TradeStore.save_csv([trade], csv_path)
    TradeStore.save_sqlite([trade], db_path)

    assert csv_path.exists()
    assert db_path.exists()
