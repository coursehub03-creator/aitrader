from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from ui.learning_center import (
    LEARNING_DATASET_SCHEMAS,
    build_learning_diagnostics,
    classify_learning_trend,
    classify_readiness,
    compute_learning_health_summary,
    compute_rolling_performance,
    extract_best_configuration_per_symbol,
    generate_learning_warnings,
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


def test_load_learning_data_handles_malformed_metadata_json(tmp_path) -> None:
    metadata_path = tmp_path / "learning_metadata.json"
    metadata_path.write_text("{ broken", encoding="utf-8")
    payload = load_learning_data(tmp_path)
    assert payload["metadata"] == {}


def test_rolling_performance_summary() -> None:
    rows = []
    for i in range(1, 121):
        rows.append({"outcome": "WIN" if i % 3 else "LOSS", "pnl": 1.5 if i % 3 else -1.0, "close_time": f"2026-01-{(i % 28) + 1:02d}T00:00:00+00:00"})
    rolling = compute_rolling_performance(pd.DataFrame(rows))
    assert rolling["last_20"]["trades"] == 20
    assert rolling["last_50"]["trades"] == 50
    assert rolling["last_100"]["trades"] == 100


def test_learning_trend_classification_market_closed_waiting() -> None:
    trend, reason = classify_learning_trend(
        historical_score=0.62,
        recent_score=0.64,
        combined_score=0.63,
        rolling={"last_20": {"average_pnl": 0.2}, "last_50": {"average_pnl": 0.1}, "last_100": {"average_pnl": 0.1, "trades": 10}},
        closed_paper_trades=8,
        market_status="closed",
    )
    assert trend == "market_closed_waiting"
    assert "Market closed" in reason


def test_readiness_classification_stable_monitored_use() -> None:
    status, reason = classify_readiness(
        metrics={"closed_paper_trades": 75},
        trend_status="stable",
        combined_score=0.66,
        forward_quality="strong",
    )
    assert status == "stable_enough_for_monitored_use"
    assert "Evidence quality" in reason


def test_warning_generation_and_no_paper_trades_empty_state() -> None:
    warnings = generate_learning_warnings(
        metrics={"total_paper_trades": 0, "closed_paper_trades": 0, "max_drawdown": 0.0, "expectancy": 0.0},
        rolling={"last_20": {"trades": 0}},
        trend_status="insufficient_data",
        market_status="closed",
    )
    titles = {w["title"] for w in warnings}
    assert "No paper trades yet" in titles
    assert "Market closed context" in titles


def test_market_closed_learning_context_in_diagnostics() -> None:
    diagnostics = build_learning_diagnostics(
        active=pd.DataFrame([{"symbol": "EURUSD", "strategy_name": "trend_rsi", "historical_score": 0.7, "recent_score": 0.7, "combined_score": 0.7, "strategy_state": "active", "trade_count": 3, "learning_confidence": 0.5}]),
        candidates=pd.DataFrame(columns=["strategy_name"]),
        paper_trades=pd.DataFrame(columns=["outcome", "pnl"]),
        historical_validation=pd.DataFrame([{"symbol": "EURUSD"}]),
        state_changes=pd.DataFrame(columns=["event_type", "new_state"]),
        events=pd.DataFrame(columns=["message"]),
        market_status="closed",
    )
    assert diagnostics["trend_status"] in {"market_closed_waiting", "insufficient_data"}
    assert diagnostics["evidence_quality"]["sample_sufficiency"] == "insufficient"
