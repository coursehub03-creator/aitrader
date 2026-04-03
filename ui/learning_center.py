"""Utilities for self-learning control center data shaping and health summaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

LOGGER = logging.getLogger(__name__)

STATE_BADGES = {
    "active": "🟢 Active",
    "probation": "🟠 Probation",
    "candidate": "🟣 Candidate",
    "disabled": "⚫ Disabled",
    "archived": "⚪ Archived",
}

LEARNING_DATASET_SCHEMAS: dict[str, list[str]] = {
    "active": [
        "strategy_name",
        "symbol",
        "timeframe",
        "strategy_state",
        "historical_score",
        "recent_score",
        "combined_score",
        "learning_confidence",
        "trade_count",
        "win_rate",
        "expectancy",
        "max_drawdown",
        "last_promoted_time",
        "state_label",
        "parameter_summary",
        "blocked_reason",
        "lifecycle_reason",
        "sample_size",
    ],
    "candidates": [
        "strategy_name",
        "symbol",
        "timeframe",
        "parameter_summary",
        "historical_score",
        "recent_score",
        "combined_score",
        "promotion_eligibility",
        "strategy_state",
        "sample_size",
        "blocked_reason",
        "lifecycle_reason",
    ],
    "state_changes": ["timestamp", "strategy", "symbol", "previous_state", "new_state", "reason", "event_type"],
    "historical_validation": [
        "timestamp",
        "symbol",
        "timeframe",
        "strategy",
        "rank",
        "train_windows",
        "train_total_trades",
        "train_win_rate",
        "train_loss_rate",
        "train_net_pnl",
        "train_max_drawdown",
        "train_profit_factor",
        "train_expectancy",
        "train_score",
        "total_trades",
        "win_rate",
        "loss_rate",
        "net_pnl",
        "max_drawdown",
        "profit_factor",
        "expectancy",
        "score",
        "params",
        "best_in_symbol_timeframe",
        "explainability",
    ],
    "paper_trades": [
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
        "timeframe",
        "strategy",
        "result",
        "signal_strength",
        "market_conditions",
        "news_status",
        "spread_state",
        "session_state",
    ],
    "events": ["timestamp", "event_type", "strategy", "symbol", "message"],
    "best_config": [
        "symbol",
        "strategy_name",
        "parameter_summary",
        "historical_score",
        "recent_score",
        "combined_score",
        "current_state",
        "last_updated",
    ],
}


@dataclass(slots=True)
class LearningHealthSummary:
    status: str
    status_reason: str
    last_optimization_run: str
    last_historical_validation_run: str
    last_paper_trade_update: str
    active_strategies: int
    candidate_strategies: int
    disabled_strategies: int
    open_paper_trades: int
    completed_paper_trades: int


def _safe_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        stamp = pd.Timestamp(text)
        as_dt = stamp.to_pydatetime()
        return as_dt if as_dt.tzinfo else as_dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def safe_read_csv(path: Path, columns: list[str], dataset_name: str = "dataset") -> pd.DataFrame:
    try:
        frame = pd.read_csv(path)
    except (FileNotFoundError, pd.errors.EmptyDataError) as exc:
        LOGGER.warning("Learning dataset '%s' is missing/empty at %s: %s", dataset_name, path, exc)
        return pd.DataFrame(columns=columns)
    except pd.errors.ParserError as exc:
        LOGGER.warning("Learning dataset '%s' is malformed at %s: %s", dataset_name, path, exc)
        return pd.DataFrame(columns=columns)
    except Exception as exc:  # pragma: no cover - defensive fallback
        LOGGER.warning("Learning dataset '%s' could not be loaded from %s: %s", dataset_name, path, exc)
        return pd.DataFrame(columns=columns)

    for column in columns:
        if column not in frame.columns:
            frame[column] = ""
    return frame[columns]


def load_learning_data(base_dir: str | Path = "logs/learning") -> dict[str, pd.DataFrame | dict[str, Any]]:
    root = Path(base_dir)
    datasets: dict[str, pd.DataFrame | dict[str, Any]] = {
        "active": safe_read_csv(root / "active_strategies.csv", LEARNING_DATASET_SCHEMAS["active"], dataset_name="active_strategies"),
        "candidates": safe_read_csv(root / "candidate_strategies.csv", LEARNING_DATASET_SCHEMAS["candidates"], dataset_name="candidate_strategies"),
        "state_changes": safe_read_csv(root / "strategy_state_changes.csv", LEARNING_DATASET_SCHEMAS["state_changes"], dataset_name="strategy_state_changes"),
        "historical_validation": safe_read_csv(root / "historical_validation.csv", LEARNING_DATASET_SCHEMAS["historical_validation"], dataset_name="historical_validation"),
        "events": safe_read_csv(root / "learning_events.csv", LEARNING_DATASET_SCHEMAS["events"], dataset_name="learning_events"),
        "best_config": safe_read_csv(root / "best_configurations.csv", LEARNING_DATASET_SCHEMAS["best_config"], dataset_name="best_configurations"),
        "paper_trades": pd.DataFrame(columns=LEARNING_DATASET_SCHEMAS["paper_trades"]),
    }

    metadata_path = root / "learning_metadata.json"
    if metadata_path.exists():
        try:
            raw = metadata_path.read_text(encoding="utf-8").strip()
            datasets["metadata"] = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            LOGGER.warning("Learning metadata is malformed at %s: %s", metadata_path, exc)
            datasets["metadata"] = {}
        except Exception as exc:  # pragma: no cover - defensive fallback
            LOGGER.warning("Learning metadata could not be loaded at %s: %s", metadata_path, exc)
            datasets["metadata"] = {}
    else:
        datasets["metadata"] = {}
    return datasets


def prepare_state_changes(frame: pd.DataFrame, limit: int = 100) -> pd.DataFrame:
    if frame.empty:
        return frame
    prepared = frame.copy()
    prepared["timestamp"] = prepared["timestamp"].astype(str)
    prepared["explanation"] = prepared["reason"].fillna("")
    prepared["state_transition"] = prepared["previous_state"].astype(str) + " → " + prepared["new_state"].astype(str)
    return prepared.sort_values("timestamp", ascending=False).head(limit).reset_index(drop=True)


def _staleness_bucket(stamp: datetime | None, now: datetime) -> str:
    if stamp is None:
        return "needs_attention"
    age = now - stamp
    if age <= timedelta(hours=6):
        return "healthy"
    if age <= timedelta(hours=24):
        return "stale"
    return "needs_attention"


def compute_learning_health_summary(
    active: pd.DataFrame,
    candidates: pd.DataFrame,
    paper_trades: pd.DataFrame,
    metadata: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> LearningHealthSummary:
    meta = metadata or {}
    now_dt = now or datetime.now(timezone.utc)

    last_opt = _safe_timestamp(meta.get("last_optimization_run"))
    last_hist = _safe_timestamp(meta.get("last_historical_validation_run"))
    last_paper = _safe_timestamp(meta.get("last_paper_trade_update"))

    buckets = [_staleness_bucket(last_opt, now_dt), _staleness_bucket(last_hist, now_dt), _staleness_bucket(last_paper, now_dt)]
    status = "healthy"
    if "needs_attention" in buckets:
        status = "needs_attention"
    elif "stale" in buckets:
        status = "stale"

    status_reason = {
        "healthy": "Learning loop is up to date.",
        "stale": "Some learning inputs are older than 6 hours.",
        "needs_attention": "Learning loop is missing recent optimizer/validation/paper updates.",
    }[status]

    active_count = int(len(active))
    candidate_count = int(len(candidates))
    disabled_count = int((active.get("strategy_state", pd.Series(dtype=str)).astype(str).str.lower() == "disabled").sum())
    open_trades = int((paper_trades.get("outcome", pd.Series(dtype=str)).astype(str).str.upper() == "OPEN").sum()) if not paper_trades.empty else 0
    completed = int(len(paper_trades) - open_trades) if not paper_trades.empty else 0

    return LearningHealthSummary(
        status=status,
        status_reason=status_reason,
        last_optimization_run=last_opt.isoformat() if last_opt else "n/a",
        last_historical_validation_run=last_hist.isoformat() if last_hist else "n/a",
        last_paper_trade_update=last_paper.isoformat() if last_paper else "n/a",
        active_strategies=active_count,
        candidate_strategies=candidate_count,
        disabled_strategies=disabled_count,
        open_paper_trades=open_trades,
        completed_paper_trades=completed,
    )


def extract_best_configuration_per_symbol(active: pd.DataFrame) -> pd.DataFrame:
    if active.empty:
        return pd.DataFrame(
            columns=[
                "symbol",
                "strategy_name",
                "parameter_summary",
                "historical_score",
                "recent_score",
                "current_state",
                "last_updated",
            ]
        )

    frame = active.copy()
    frame["recent_score"] = pd.to_numeric(frame.get("recent_score"), errors="coerce").fillna(-999999)
    frame["historical_score"] = pd.to_numeric(frame.get("historical_score"), errors="coerce").fillna(-999999)
    if "combined_score" not in frame.columns:
        frame["combined_score"] = frame["recent_score"] * 0.65 + frame["historical_score"] * 0.35

    ranked = frame.sort_values(["symbol", "combined_score"], ascending=[True, False]).groupby("symbol", as_index=False).head(1)
    ranked["last_updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    return ranked.rename(
        columns={
            "strategy_state": "current_state",
        }
    )[
        [
            "symbol",
            "strategy_name",
            "parameter_summary",
            "historical_score",
            "recent_score",
            "combined_score",
            "current_state",
            "last_updated",
        ]
    ].reset_index(drop=True)
