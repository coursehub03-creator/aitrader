from __future__ import annotations

from pathlib import Path

import pandas as pd

from learning.persistence import LearningPersistence, StorageLayout


def test_storage_layout_created(tmp_path: Path) -> None:
    persistence = LearningPersistence(StorageLayout(root=tmp_path))

    assert persistence.layout.market_history_dir.exists()
    assert persistence.layout.paper_trades_dir.exists()
    assert persistence.layout.learning_dir.exists()
    assert persistence.layout.optimizer_dir.exists()
    assert persistence.layout.snapshots_dir.exists()
    assert persistence.layout.state_dir.exists()
    assert persistence.layout.db_dir.exists()


def test_safe_json_csv_and_table_reading_handles_missing_empty_and_malformed(tmp_path: Path) -> None:
    persistence = LearningPersistence(StorageLayout(root=tmp_path))

    missing = persistence.safe_read_json(tmp_path / "missing.json", default={"ok": True})
    assert missing == {"ok": True}

    malformed_json = tmp_path / "bad.json"
    malformed_json.write_text("{bad", encoding="utf-8")
    assert persistence.safe_read_json(malformed_json, default={}) == {}

    empty_csv = tmp_path / "empty.csv"
    empty_csv.write_text("", encoding="utf-8")
    loaded_empty = persistence.safe_read_csv(empty_csv, ["a", "b"])
    assert list(loaded_empty.columns) == ["a", "b"]
    assert loaded_empty.empty

    malformed_csv = tmp_path / "bad.csv"
    malformed_csv.write_text('"unterminated', encoding="utf-8")
    loaded_bad = persistence.safe_read_csv(malformed_csv, ["a", "b"])
    assert list(loaded_bad.columns) == ["a", "b"]
    assert loaded_bad.empty

    missing_table = persistence.safe_read_table("does_not_exist", ["x", "y"])
    assert missing_table.empty
    assert list(missing_table.columns) == ["x", "y"]


def test_persists_structured_and_state_artifacts(tmp_path: Path) -> None:
    persistence = LearningPersistence(StorageLayout(root=tmp_path))

    rec = {"timestamp": "2026-04-03T00:00:00+00:00", "symbol": "EURUSD", "action": "BUY"}
    alert = {"timestamp": "2026-04-03T00:00:01+00:00", "symbol": "EURUSD", "status": "sent"}
    persistence.append_recommendation_history(rec)
    persistence.append_alert_history(alert)

    rec_rows = persistence.safe_read_table("recommendation_history", ["timestamp", "symbol", "action"])
    alert_rows = persistence.safe_read_table("alert_history", ["timestamp", "symbol", "status"])
    assert len(rec_rows) == 1
    assert len(alert_rows) == 1

    paper_history = pd.DataFrame([
        {"symbol": "EURUSD", "strategy": "trend_rsi", "outcome": "WIN", "pnl": 12.0},
        {"symbol": "EURUSD", "strategy": "breakout_atr", "outcome": "OPEN", "pnl": 0.0},
    ])
    paper_path = persistence.save_paper_trade_history(paper_history)
    assert paper_path.exists()

    open_trades = [{"symbol": "EURUSD", "strategy": "breakout_atr", "entry": 1.1}]
    open_path = persistence.save_open_paper_trades(open_trades)
    assert open_path.exists()
    assert persistence.load_open_paper_trades() == open_trades

    historical = pd.DataFrame([{"symbol": "EURUSD", "strategy": "trend_rsi", "score": 42.5}])
    historical_path = persistence.save_historical_validation_results(historical)
    assert historical_path.exists()

    optimizer = pd.DataFrame([{"strategy": "trend_rsi", "score": 47.0, "best_params": "{}"}])
    optimizer_path = persistence.save_optimizer_results(optimizer, "EURUSD", "M5")
    assert optimizer_path.exists()

    persistence.append_strategy_state_change({"symbol": "EURUSD", "strategy": "trend_rsi", "new_state": "active"})
    persistence.append_strategy_score_snapshot(
        {
            "timestamp": "2026-04-03T00:00:03+00:00",
            "symbol": "EURUSD",
            "strategy_name": "trend_rsi",
            "historical_score": 44.0,
            "recent_score": 41.0,
            "combined_score": 42.2,
            "lifecycle_state": "active",
        }
    )
    persistence.append_lifecycle_event(
        symbol="EURUSD",
        strategy="trend_rsi",
        event_type="promoted",
        previous_state="candidate",
        new_state="promoted",
        reason="passed thresholds",
    )
    state_rows = persistence.safe_read_table("strategy_state_changes", ["symbol", "strategy", "new_state"])
    lifecycle_rows = persistence.safe_read_table(
        "strategy_lifecycle_events",
        ["symbol", "strategy", "event_type", "previous_state", "new_state", "reason"],
    )
    score_rows = persistence.safe_read_table(
        "strategy_score_snapshots",
        ["symbol", "strategy_name", "combined_score", "lifecycle_state"],
    )
    assert len(state_rows) == 1
    assert lifecycle_rows.iloc[0]["event_type"] == "promoted"
    assert len(score_rows) == 1

    best_path = persistence.save_best_params("EURUSD", "M5", "trend_rsi", {"ema_fast": 20}, 42.5)
    assert best_path.exists()
    best = persistence.load_best_params("EURUSD", "M5")
    assert best["trend_rsi"]["best_historical_params"]["ema_fast"] == 20

    profile_path = persistence.save_symbol_profile("EURUSD", "M5", {"risk_mode": "balanced"})
    assert profile_path.exists()
    assert persistence.load_symbol_profile("EURUSD", "M5")["risk_mode"] == "balanced"

    health_path = persistence.save_learning_health({"status": "healthy", "open_trades": 1})
    assert health_path.exists()
    persistence.append_learning_health({"timestamp": "2026-04-03T00:00:02+00:00", "status": "healthy"})
    health_rows = persistence.safe_read_table("learning_health", ["timestamp", "status"])
    assert len(health_rows) == 1


def test_market_history_writes_csv_and_parquet_fallback(tmp_path: Path) -> None:
    persistence = LearningPersistence(StorageLayout(root=tmp_path))
    frame = pd.DataFrame([{"time": "2026-01-01T00:00:00", "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05, "volume": 100}])

    csv_path = persistence.safe_write_market_history(persistence.layout.market_history_dir / "EURUSD_M5", frame, prefer_parquet=False)
    assert csv_path.suffix == ".csv"
    assert csv_path.exists()

    maybe_parquet_path = persistence.safe_write_market_history(
        persistence.layout.market_history_dir / "XAUUSD_M15",
        frame,
        prefer_parquet=True,
    )
    assert maybe_parquet_path.exists()
    assert maybe_parquet_path.suffix in {".parquet", ".csv"}
