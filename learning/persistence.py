"""Robust persistence layer for learning, monitoring, history, optimizer artifacts, and strategy state."""

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
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def market_history_dir(self) -> Path:
        return self.data_dir / "market_history"

    @property
    def paper_trades_dir(self) -> Path:
        return self.data_dir / "paper_trades"

    @property
    def learning_dir(self) -> Path:
        return self.data_dir / "learning"

    @property
    def optimizer_dir(self) -> Path:
        return self.data_dir / "optimizer"

    @property
    def snapshots_dir(self) -> Path:
        return self.data_dir / "snapshots"

    @property
    def state_dir(self) -> Path:
        return self.root / "state"

    @property
    def db_dir(self) -> Path:
        return self.root / "db"

    @property
    def learning_db_path(self) -> Path:
        return self.db_dir / "learning.sqlite3"

    def ensure(self) -> None:
        for path in (
            self.market_history_dir,
            self.paper_trades_dir,
            self.learning_dir,
            self.optimizer_dir,
            self.snapshots_dir,
            self.state_dir,
            self.db_dir,
            self.state_dir / "symbol_profiles",
            self.state_dir / "best_params",
        ):
            path.mkdir(parents=True, exist_ok=True)


class LearningPersistence:
    """Safe storage APIs with SQLite (structured), JSON (active state), and CSV/Parquet (history)."""

    def __init__(self, layout: StorageLayout | None = None) -> None:
        self.layout = layout or StorageLayout()
        self.layout.ensure()
        self.learning_db_path = self.layout.learning_db_path

    @staticmethod
    def _timestamp_utc() -> str:
        return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")

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
        except (TypeError, json.JSONDecodeError):
            return default

    @staticmethod
    def safe_write_json(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

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

    @staticmethod
    def safe_write_csv(path: Path, frame: pd.DataFrame) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, index=False)

    @staticmethod
    def safe_read_parquet(path: Path, columns: list[str]) -> pd.DataFrame:
        try:
            frame = pd.read_parquet(path)
        except FileNotFoundError:
            return pd.DataFrame(columns=columns)
        except Exception:
            return pd.DataFrame(columns=columns)

        for column in columns:
            if column not in frame.columns:
                frame[column] = ""
        return frame[columns]

    def safe_write_market_history(self, path: Path, frame: pd.DataFrame, prefer_parquet: bool = False) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        if prefer_parquet:
            parquet_path = path.with_suffix(".parquet")
            try:
                frame.to_parquet(parquet_path, index=False)
                return parquet_path
            except Exception:
                # Fall back to CSV if parquet dependencies are unavailable.
                pass
        csv_path = path.with_suffix(".csv")
        frame.to_csv(csv_path, index=False)
        return csv_path

    def upsert_table(self, table_name: str, frame: pd.DataFrame, if_exists: str = "append") -> None:
        self.layout.db_dir.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.learning_db_path) as conn:
            frame.to_sql(table_name, conn, if_exists=if_exists, index=False)

    def safe_read_table(self, table_name: str, columns: list[str], limit: int | None = None) -> pd.DataFrame:
        query = f"SELECT * FROM {table_name}"
        if limit is not None:
            query = f"{query} ORDER BY rowid DESC LIMIT {int(limit)}"
        try:
            with sqlite3.connect(self.learning_db_path) as conn:
                frame = pd.read_sql_query(query, conn)
        except Exception:
            return pd.DataFrame(columns=columns)

        for column in columns:
            if column not in frame.columns:
                frame[column] = ""
        return frame[columns]

    def append_recommendation_history(self, row: dict[str, Any]) -> None:
        self.upsert_table("recommendation_history", pd.DataFrame([row]), if_exists="append")

    def append_alert_history(self, row: dict[str, Any]) -> None:
        self.upsert_table("alert_history", pd.DataFrame([row]), if_exists="append")

    def save_paper_trade_history(self, frame: pd.DataFrame) -> Path:
        self.upsert_table("paper_trade_history", frame, if_exists="replace")
        path = self.layout.paper_trades_dir / "paper_trade_history.csv"
        self.safe_write_csv(path, frame)
        return path

    def save_open_paper_trades(self, rows: list[dict[str, Any]]) -> Path:
        path = self.layout.state_dir / "open_paper_trades.json"
        self.safe_write_json(path, rows)
        return path

    def load_open_paper_trades(self) -> list[dict[str, Any]]:
        payload = self.safe_read_json(self.layout.state_dir / "open_paper_trades.json", default=[])
        return payload if isinstance(payload, list) else []

    def save_historical_validation_results(self, frame: pd.DataFrame) -> Path:
        self.upsert_table("historical_validation_results", frame, if_exists="replace")
        path = self.layout.learning_dir / "historical_validation.csv"
        self.safe_write_csv(path, frame)
        return path

    def save_optimizer_results(self, frame: pd.DataFrame, symbol: str, timeframe: str) -> Path:
        payload = frame.copy()
        payload["saved_at"] = self._timestamp_utc()
        self.upsert_table("optimizer_results", payload, if_exists="append")
        path = self.layout.optimizer_dir / f"optimizer_{symbol.upper()}_{timeframe.upper()}_{datetime.now(tz=timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.csv"
        self.safe_write_csv(path, payload)
        return path

    def append_strategy_state_change(self, row: dict[str, Any]) -> None:
        self.upsert_table("strategy_state_changes", pd.DataFrame([row]), if_exists="append")

    def append_lifecycle_event(
        self,
        *,
        symbol: str,
        strategy: str,
        event_type: str,
        previous_state: str,
        new_state: str,
        reason: str,
    ) -> None:
        row = {
            "timestamp": self._timestamp_utc(),
            "symbol": symbol,
            "strategy": strategy,
            "event_type": event_type,
            "previous_state": previous_state,
            "new_state": new_state,
            "reason": reason,
        }
        self.upsert_table("strategy_lifecycle_events", pd.DataFrame([row]), if_exists="append")

    def append_learning_health(self, row: dict[str, Any]) -> None:
        self.upsert_table("learning_health", pd.DataFrame([row]), if_exists="append")

    def save_learning_health(self, payload: dict[str, Any]) -> Path:
        path = self.layout.state_dir / "learning_health.json"
        self.safe_write_json(path, payload)
        return path

    def save_strategy_state(self, state_payload: dict[str, Any]) -> Path:
        path = self.layout.state_dir / "active_strategy_state.json"
        self.safe_write_json(path, state_payload)
        return path

    def save_symbol_profile(self, symbol: str, timeframe: str, profile: dict[str, Any]) -> Path:
        path = self.layout.state_dir / "symbol_profiles" / f"{symbol.upper()}_{timeframe.upper()}.json"
        self.safe_write_json(path, profile)
        return path

    def load_symbol_profile(self, symbol: str, timeframe: str) -> dict[str, Any]:
        path = self.layout.state_dir / "symbol_profiles" / f"{symbol.upper()}_{timeframe.upper()}.json"
        payload = self.safe_read_json(path, default={})
        return payload if isinstance(payload, dict) else {}

    def save_best_params(self, symbol: str, timeframe: str, strategy_name: str, params: dict[str, Any], score: float) -> Path:
        path = self.layout.state_dir / "best_params" / f"{symbol.upper()}_{timeframe.upper()}.json"
        payload = self.safe_read_json(path, default={})
        payload = payload if isinstance(payload, dict) else {}
        payload[strategy_name] = {
            "best_historical_params": params,
            "historical_score": float(score),
            "updated_at": self._timestamp_utc(),
        }
        self.safe_write_json(path, payload)
        return path

    def load_best_params(self, symbol: str, timeframe: str) -> dict[str, Any]:
        path = self.layout.state_dir / "best_params" / f"{symbol.upper()}_{timeframe.upper()}.json"
        payload = self.safe_read_json(path, default={})
        return payload if isinstance(payload, dict) else {}

    # Backwards-compat wrappers used in existing code paths.
    def append_state_change(self, row: dict[str, Any]) -> None:
        self.append_strategy_state_change(row)

    def save_historical_validation(self, frame: pd.DataFrame) -> None:
        self.save_historical_validation_results(frame)

    def save_paper_trades(self, frame: pd.DataFrame) -> None:
        self.save_paper_trade_history(frame)
