from __future__ import annotations

import argparse
import json
from datetime import datetime

import pytest

from app import main as cli


class _FakeRecommendation:
    def __init__(self, action: str = "BUY", market_status: str = "open", news_status: str = "clear") -> None:
        self.symbol = "EURUSD"
        self.timeframe = "M5"
        self.timestamp = datetime(2026, 1, 1, 0, 0, 0)
        self.market_status = market_status
        self.news_status = news_status
        self.selected_strategy = "trend_rsi"
        self.action = action
        self.entry = 1.1
        self.stop_loss = 1.09
        self.take_profit = 1.12
        self.confidence = 0.7
        self.risk_reward = 2.0
        self.reasons = ["test reason"]


class _FakeEngine:
    def __init__(self, outcomes: list[object]) -> None:
        self._outcomes = outcomes
        self.calls = 0

    def generate(self, symbol: str, timeframe: str):
        outcome = self._outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    @staticmethod
    def format_for_terminal(recommendation: _FakeRecommendation) -> str:
        return f"REC {recommendation.symbol} {recommendation.action}"


def test_build_parser_accepts_watch_and_interval() -> None:
    parser = cli.build_parser()

    args = parser.parse_args(["--symbol", "EURUSD", "--watch", "--interval", "120"])

    assert args.watch is True
    assert args.interval == 120


def test_run_single_cycle_persists_log(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "MONITOR_LOG_PATH", tmp_path / "monitor.jsonl")
    engine = _FakeEngine([_FakeRecommendation(action="BUY", market_status="open", news_status="blocked")])
    args = argparse.Namespace(symbol="EURUSD", timeframe="M5", watch=False, interval=300)

    cli.run(engine, args)

    output = capsys.readouterr().out
    assert "Market status: open" in output
    assert "Trading blocked by news: yes" in output
    assert "REC EURUSD BUY" in output

    lines = (tmp_path / "monitor.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["cycle"] == 1
    assert payload["recommendation"]["action"] == "BUY"


def test_run_watch_mode_retries_after_failure(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "MONITOR_LOG_PATH", tmp_path / "monitor.jsonl")

    sleep_calls = {"count": 0}

    def _sleep(seconds: int) -> None:
        sleep_calls["count"] += 1
        if sleep_calls["count"] >= 2:
            raise KeyboardInterrupt()

    monkeypatch.setattr(cli.time, "sleep", _sleep)

    engine = _FakeEngine([RuntimeError("mt5 disconnected"), _FakeRecommendation(action="NO_TRADE", market_status="mt5_unavailable")])
    args = argparse.Namespace(symbol="EURUSD", timeframe="M5", watch=True, interval=1)

    with pytest.raises(KeyboardInterrupt):
        cli.run(engine, args)

    output = capsys.readouterr().out
    assert "Cycle 1 failed" in output
    assert "Market status: mt5_unavailable" in output

    lines = (tmp_path / "monitor.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    second = json.loads(lines[1])
    assert first["error"] == "mt5 disconnected"
    assert second["recommendation"]["market_status"] == "mt5_unavailable"
