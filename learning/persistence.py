"""Persistence layer for learning, paper trading, optimizer artifacts, and strategy state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any

import pandas as pd


@dataclass(slots=True)
class StorageLayout:
    root: Path = Path(".")

    @property
    def market_history_dir(self) -> Path:
        return self.root / "data" / "market_history"

    @property
    def paper_trades_dir(self) -> Path:
        return self.root / "data" / "paper_trades"

    @property
    def learning_dir(self) -> Path:
        return self.root / "data" / "learning"

    @property
    def optimizer_dir(self) -> Path:
        return self.root / "data" / "optimizer"

    @property
    def snapshots_dir(self) -> Path:
        return self.root / "data" / "snapshots"

    @property
    def state_dir(self) -> Path:
        return self.root / "state"

    @property
    def db_dir(self) -> Path:
        return self.root / "db"

    def ensure(self) -> None:
        for path in (
            self.market_history_dir,
            self.paper_trades_dir,
            self.learning_dir,
            self.optimizer_dir,
            self.snapshots_dir,
            self.state_dir,
            self.db_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


class LearningPersistence:
    def __init__(self, layout: StorageLayout | None = None) -> None:
        self.layout = layout or StorageLayout()
        self.layout.ensure()
        self.learning_db_path = self.layout.db_dir / "learning.sqlite3"

    @staticmethod
    def safe_read_json(path: Path, default: Any) -> Any:
        try:
            raw = path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return default
        except Exception:
            return default
        if not raw:
            return default
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return default

    @staticmethod
    def safe_write_json(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @staticmethod
    def safe_read_csv(path: Path, columns: list[str]) -> pd.DataFrame:
        try:
            frame = pd.read_csv(path)
        except (FileNotFoundError, pd.errors.EmptyDataError, pd.errors.ParserError):
            return pd.DataFrame(columns=columns)
        except Exception:
            return pd.DataFrame(columns=columns)

        for column in columns:
            if column not in frame.columns:
                frame[column] = ""
        return frame[columns]

    def upsert_table(self, table_name: str, frame: pd.DataFrame, if_exists: str = "append") -> None:
        self.layout.db_dir.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.learning_db_path) as conn:
            frame.to_sql(table_name, conn, if_exists=if_exists, index=False)

    def save_symbol_profile(self, symbol: str, timeframe: str, profile: dict[str, Any]) -> Path:
        path = self.layout.state_dir / "symbol_profiles" / f"{symbol.upper()}_{timeframe.upper()}.json"
        self.safe_write_json(path, profile)
        return path

    def save_best_params(self, symbol: str, timeframe: str, strategy_name: str, params: dict[str, Any], score: float) -> Path:
        path = self.layout.state_dir / "best_params" / f"{symbol.upper()}_{timeframe.upper()}.json"
        payload = self.safe_read_json(path, default={})
        payload.setdefault(strategy_name, {})
        payload[strategy_name] = {
            "best_historical_params": params,
            "historical_score": float(score),
            "updated_at": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        }
        self.safe_write_json(path, payload)
        return path

    def save_strategy_state(self, state_payload: dict[str, Any]) -> Path:
        path = self.layout.state_dir / "active_strategy_state.json"
        self.safe_write_json(path, state_payload)
        return path

    def append_state_change(self, row: dict[str, Any]) -> None:
        frame = pd.DataFrame([row])
        self.upsert_table("strategy_state_changes", frame, if_exists="append")

    def append_learning_health(self, row: dict[str, Any]) -> None:
        frame = pd.DataFrame([row])
        self.upsert_table("learning_health", frame, if_exists="append")

    def append_alert_history(self, row: dict[str, Any]) -> None:
        frame = pd.DataFrame([row])
        self.upsert_table("alert_history", frame, if_exists="append")

    def save_historical_validation(self, frame: pd.DataFrame) -> None:
        self.upsert_table("historical_validation", frame, if_exists="replace")

    def save_paper_trades(self, frame: pd.DataFrame) -> None:
        self.upsert_table("paper_trades", frame, if_exists="replace")

