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


def test_safe_json_and_csv_reading_handles_missing_empty_and_malformed(tmp_path: Path) -> None:
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


def test_save_best_params_and_sqlite_tables(tmp_path: Path) -> None:
    persistence = LearningPersistence(StorageLayout(root=tmp_path))

    path = persistence.save_best_params("EURUSD", "M5", "trend_rsi", {"ema_fast": 20}, 42.5)
    assert path.exists()

    payload = persistence.safe_read_json(path, default={})
    assert payload["trend_rsi"]["historical_score"] == 42.5
    assert payload["trend_rsi"]["best_historical_params"]["ema_fast"] == 20

    frame = pd.DataFrame([{"symbol": "EURUSD", "strategy": "trend_rsi", "historical_score": 42.5}])
    persistence.save_historical_validation(frame)
    assert persistence.learning_db_path.exists()
