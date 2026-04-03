from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from ui.learning_center import (
    LEARNING_DATASET_SCHEMAS,
    compute_learning_health_summary,
    extract_best_configuration_per_symbol,
    load_learning_data,
    prepare_state_changes,
    safe_read_csv,
)


def test_load_learning_data_handles_missing_files(tmp_path) -> None:
    payload = load_learning_data(tmp_path)
    assert payload["active"].empty
    assert payload["candidates"].empty
    assert payload["state_changes"].empty
    assert payload["historical_validation"].empty
    assert payload["events"].empty
    assert payload["best_config"].empty
    assert payload["metadata"] == {}


def test_prepare_state_changes_builds_transition_columns() -> None:
    frame = pd.DataFrame(
        [
            {
                "timestamp": "2026-01-01T12:00:00+00:00",
                "strategy": "trend_rsi",
                "symbol": "EURUSD",
                "previous_state": "candidate",
                "new_state": "promoted",
                "reason": "Score and sample size thresholds met.",
                "event_type": "promotion",
            }
        ]
    )
    out = prepare_state_changes(frame)
    assert out.loc[0, "state_transition"] == "candidate → promoted"
    assert "thresholds met" in out.loc[0, "explanation"]


def test_learning_health_summary_generation() -> None:
    active = pd.DataFrame([{"strategy_name": "trend_rsi", "strategy_state": "stable"}])
    candidates = pd.DataFrame([{"strategy_name": "breakout_atr"}])
    paper = pd.DataFrame([{"outcome": "OPEN"}, {"outcome": "WIN"}])
    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    health = compute_learning_health_summary(
        active,
        candidates,
        paper,
        metadata={
            "last_optimization_run": "2026-01-02T00:00:00+00:00",
            "last_historical_validation_run": "2026-01-01T22:00:00+00:00",
            "last_paper_trade_update": "2026-01-01T23:59:00+00:00",
        },
        now=now,
    )
    assert health.status in {"healthy", "stale"}
    assert health.active_strategies == 1
    assert health.candidate_strategies == 1
    assert health.open_paper_trades == 1
    assert health.completed_paper_trades == 1


def test_extract_best_configuration_per_symbol() -> None:
    active = pd.DataFrame(
        [
            {
                "symbol": "EURUSD",
                "strategy_name": "trend_rsi",
                "parameter_summary": "{\"ema_fast\": 8}",
                "historical_score": 50,
                "recent_score": 60,
                "strategy_state": "stable",
            },
            {
                "symbol": "EURUSD",
                "strategy_name": "breakout_atr",
                "parameter_summary": "{\"atr_period\": 14}",
                "historical_score": 40,
                "recent_score": 45,
                "strategy_state": "probation",
            },
            {
                "symbol": "XAUUSD",
                "strategy_name": "breakout_atr",
                "parameter_summary": "{\"atr_period\": 10}",
                "historical_score": 70,
                "recent_score": 65,
                "strategy_state": "stable",
            },
        ]
    )
    out = extract_best_configuration_per_symbol(active)
    assert set(out["symbol"]) == {"EURUSD", "XAUUSD"}
    assert out[out["symbol"] == "EURUSD"].iloc[0]["strategy_name"] == "trend_rsi"


def test_health_summary_with_zero_trades_and_zero_active_strategies() -> None:
    health = compute_learning_health_summary(
        active=pd.DataFrame(columns=["strategy_name", "strategy_state"]),
        candidates=pd.DataFrame(columns=["strategy_name"]),
        paper_trades=pd.DataFrame(columns=["outcome"]),
        metadata={},
        now=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    assert health.active_strategies == 0
    assert health.open_paper_trades == 0
    assert health.completed_paper_trades == 0


def test_safe_read_csv_returns_empty_schema_for_missing_file(tmp_path) -> None:
    frame = safe_read_csv(tmp_path / "missing.csv", LEARNING_DATASET_SCHEMAS["candidates"], dataset_name="candidates")
    assert frame.empty
    assert list(frame.columns) == LEARNING_DATASET_SCHEMAS["candidates"]


def test_safe_read_csv_returns_empty_schema_for_empty_file(tmp_path) -> None:
    path = tmp_path / "candidate_strategies.csv"
    path.write_text("", encoding="utf-8")
    frame = safe_read_csv(path, LEARNING_DATASET_SCHEMAS["candidates"], dataset_name="candidates")
    assert frame.empty
    assert list(frame.columns) == LEARNING_DATASET_SCHEMAS["candidates"]


def test_safe_read_csv_returns_empty_schema_for_malformed_file(tmp_path) -> None:
    path = tmp_path / "candidate_strategies.csv"
    path.write_text('\"broken\nx,y,z', encoding="utf-8")
    frame = safe_read_csv(path, LEARNING_DATASET_SCHEMAS["candidates"], dataset_name="candidates")
    assert frame.empty
    assert list(frame.columns) == LEARNING_DATASET_SCHEMAS["candidates"]
