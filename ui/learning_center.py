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
        "train_avg_reward_risk",
        "train_score",
        "total_trades",
        "win_rate",
        "loss_rate",
        "net_pnl",
        "max_drawdown",
        "profit_factor",
        "expectancy",
        "avg_reward_risk",
        "score",
        "final_validation_score",
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


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        cast = float(value)
        if pd.isna(cast):
            return default
        return cast
    except (TypeError, ValueError):
        return default


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


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


def compute_paper_trade_metrics(paper_trades: pd.DataFrame) -> dict[str, float | int]:
    if paper_trades.empty:
        return {
            "total_paper_trades": 0,
            "open_paper_trades": 0,
            "closed_paper_trades": 0,
            "win_rate": 0.0,
            "loss_rate": 0.0,
            "net_pnl": 0.0,
            "average_pnl": 0.0,
            "max_drawdown": 0.0,
            "profit_factor": 0.0,
            "expectancy": 0.0,
        }

    frame = paper_trades.copy()
    frame["outcome_normalized"] = frame.get("outcome", pd.Series(dtype=str)).astype(str).str.upper()
    frame["pnl_num"] = pd.to_numeric(frame.get("pnl"), errors="coerce").fillna(0.0)
    frame["is_open"] = frame["outcome_normalized"] == "OPEN"
    closed = frame[~frame["is_open"]].copy()
    closed["is_win"] = closed["pnl_num"] > 0

    total = int(len(frame))
    open_count = int(frame["is_open"].sum())
    closed_count = int(len(closed))
    wins = int(closed["is_win"].sum()) if closed_count else 0
    losses = int(closed_count - wins)

    gross_profit = float(closed.loc[closed["pnl_num"] > 0, "pnl_num"].sum()) if closed_count else 0.0
    gross_loss = float(closed.loc[closed["pnl_num"] < 0, "pnl_num"].sum()) if closed_count else 0.0

    close_raw = closed.get("close_time", pd.Series(index=closed.index, dtype=object))
    open_raw = closed.get("open_time", pd.Series(index=closed.index, dtype=object))
    close_time = pd.to_datetime(close_raw, errors="coerce", utc=True)
    open_time = pd.to_datetime(open_raw, errors="coerce", utc=True)
    closed["time_key"] = close_time.fillna(open_time)
    closed = closed.sort_values("time_key")
    equity_curve = closed["pnl_num"].cumsum()
    rolling_peak = equity_curve.cummax()
    drawdowns = rolling_peak - equity_curve
    max_drawdown = float(drawdowns.max()) if not drawdowns.empty else 0.0

    profit_factor = float(gross_profit / abs(gross_loss)) if gross_loss < 0 else (float("inf") if gross_profit > 0 else 0.0)
    avg_pnl = float(closed["pnl_num"].mean()) if closed_count else 0.0

    return {
        "total_paper_trades": total,
        "open_paper_trades": open_count,
        "closed_paper_trades": closed_count,
        "win_rate": _safe_ratio(wins, closed_count),
        "loss_rate": _safe_ratio(losses, closed_count),
        "net_pnl": float(closed["pnl_num"].sum()) if closed_count else 0.0,
        "average_pnl": avg_pnl,
        "max_drawdown": max_drawdown,
        "profit_factor": profit_factor,
        "expectancy": avg_pnl,
    }


def compute_rolling_performance(paper_trades: pd.DataFrame, windows: tuple[int, ...] = (20, 50, 100)) -> dict[str, dict[str, float | int]]:
    frame = paper_trades.copy()
    if frame.empty:
        return {f"last_{w}": {"trades": 0, "win_rate": 0.0, "net_pnl": 0.0, "average_pnl": 0.0} for w in windows}
    frame["outcome_normalized"] = frame.get("outcome", pd.Series(dtype=str)).astype(str).str.upper()
    frame = frame[frame["outcome_normalized"] != "OPEN"].copy()
    frame["pnl_num"] = pd.to_numeric(frame.get("pnl"), errors="coerce").fillna(0.0)
    close_raw = frame.get("close_time", pd.Series(index=frame.index, dtype=object))
    open_raw = frame.get("open_time", pd.Series(index=frame.index, dtype=object))
    frame["time_key"] = pd.to_datetime(close_raw, errors="coerce", utc=True).fillna(pd.to_datetime(open_raw, errors="coerce", utc=True))
    frame = frame.sort_values("time_key")
    results: dict[str, dict[str, float | int]] = {}
    for window in windows:
        subset = frame.tail(window)
        trades = int(len(subset))
        wins = int((subset["pnl_num"] > 0).sum()) if trades else 0
        results[f"last_{window}"] = {
            "trades": trades,
            "win_rate": _safe_ratio(wins, trades),
            "net_pnl": float(subset["pnl_num"].sum()) if trades else 0.0,
            "average_pnl": float(subset["pnl_num"].mean()) if trades else 0.0,
        }
    return results


def classify_learning_trend(
    historical_score: float,
    recent_score: float,
    combined_score: float,
    rolling: dict[str, dict[str, float | int]],
    closed_paper_trades: int,
    market_status: str = "unknown",
) -> tuple[str, str]:
    if market_status == "closed" and closed_paper_trades < 20:
        return "market_closed_waiting", "Market closed and forward sample is still limited; waiting for new evidence."
    if closed_paper_trades < 20:
        return "insufficient_data", "Not enough closed paper trades yet for robust trend classification."

    short_avg = _as_float(rolling.get("last_20", {}).get("average_pnl"))
    baseline_avg = _as_float(rolling.get("last_100", {}).get("average_pnl"))
    if _as_float(rolling.get("last_100", {}).get("trades")) < 30:
        baseline_avg = _as_float(rolling.get("last_50", {}).get("average_pnl"))

    score_delta = recent_score - historical_score
    pnl_delta = short_avg - baseline_avg
    if pnl_delta > 0 and score_delta >= -0.03 and combined_score >= historical_score:
        return "improving", "Recent paper performance and learning score are improving versus baseline."
    if pnl_delta < 0 and score_delta < -0.05:
        return "degrading", "Recent paper performance and recent learning score are both below baseline."
    return "stable", "Learning metrics are within expected variance versus the longer-term baseline."


def classify_readiness(metrics: dict[str, float | int], trend_status: str, combined_score: float, forward_quality: str) -> tuple[str, str]:
    closed_trades = int(metrics.get("closed_paper_trades", 0))
    if closed_trades == 0:
        return "not_ready", "No forward paper-trade evidence yet."
    if closed_trades < 20:
        return "learning_but_too_early", "System is learning, but forward sample is too small."
    if combined_score >= 0.6 and forward_quality in {"weak", "limited"}:
        return "historically_strong_forward_weak", "Historical quality is acceptable but forward evidence is still weak."
    if trend_status in {"stable", "improving"} and combined_score >= 0.55:
        return "stable_enough_for_monitored_use", "Evidence quality and trend support monitored operator use."
    return "not_ready", "Current diagnostics do not yet support trust readiness."


def generate_learning_warnings(
    metrics: dict[str, float | int],
    rolling: dict[str, dict[str, float | int]],
    trend_status: str,
    market_status: str,
) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    total = int(metrics.get("total_paper_trades", 0))
    closed = int(metrics.get("closed_paper_trades", 0))
    if total == 0:
        warnings.append({"severity": "info", "title": "No paper trades yet", "message": "Historical learning may exist, but forward learning is not established yet."})
    if closed < 20 and total > 0:
        warnings.append({"severity": "warning", "title": "Too few trades", "message": "At least 20 closed paper trades are recommended for reliable trend diagnostics."})
    if int(rolling.get("last_20", {}).get("trades", 0)) < 10 and total > 0:
        warnings.append({"severity": "warning", "title": "Insufficient recent sample", "message": "Recent window has too few trades; keep monitor mode running for more evidence."})
    if _as_float(metrics.get("max_drawdown")) > 5.0:
        warnings.append({"severity": "warning", "title": "High drawdown", "message": "Max drawdown is elevated versus operator comfort thresholds."})
    if _as_float(metrics.get("expectancy")) < 0:
        warnings.append({"severity": "warning", "title": "Poor expectancy", "message": "Average closed-trade expectancy is negative."})
    if trend_status == "degrading":
        warnings.append({"severity": "critical", "title": "Unstable performance", "message": "Recent diagnostics indicate degradation versus longer-term baseline."})
    if market_status == "closed":
        warnings.append({"severity": "info", "title": "Market closed context", "message": "Market is closed today; no new forward evidence is expected until next open session."})
    return warnings


def build_learning_diagnostics(
    active: pd.DataFrame,
    candidates: pd.DataFrame,
    paper_trades: pd.DataFrame,
    historical_validation: pd.DataFrame,
    state_changes: pd.DataFrame,
    events: pd.DataFrame,
    market_status: str,
) -> dict[str, Any]:
    metrics = compute_paper_trade_metrics(paper_trades)
    rolling = compute_rolling_performance(paper_trades)

    strategies = pd.concat([active, candidates], ignore_index=True) if not active.empty or not candidates.empty else pd.DataFrame()
    if strategies.empty:
        historical_score = recent_score = combined_score = 0.0
    else:
        historical_score = float(pd.to_numeric(strategies.get("historical_score"), errors="coerce").fillna(0.0).mean())
        recent_score = float(pd.to_numeric(strategies.get("recent_score"), errors="coerce").fillna(0.0).mean())
        combined_score = float(pd.to_numeric(strategies.get("combined_score"), errors="coerce").fillna(0.0).mean())

    trend_status, trend_reason = classify_learning_trend(
        historical_score=historical_score,
        recent_score=recent_score,
        combined_score=combined_score,
        rolling=rolling,
        closed_paper_trades=int(metrics["closed_paper_trades"]),
        market_status=market_status,
    )

    hist_rows = int(len(historical_validation))
    closed = int(metrics["closed_paper_trades"])
    historical_quality = "strong" if hist_rows >= 25 else ("limited" if hist_rows >= 8 else "weak")
    forward_quality = "strong" if closed >= 100 else ("limited" if closed >= 20 else "weak")
    combined_quality = "strong" if historical_quality == "strong" and forward_quality in {"strong", "limited"} else "limited" if hist_rows > 0 or closed > 0 else "weak"
    evidence_basis = "historical+forward" if closed >= 20 else "historical_only"
    sample_sufficiency = "sufficient" if closed >= 20 else "insufficient"

    readiness, readiness_reason = classify_readiness(metrics, trend_status, combined_score, forward_quality)
    warnings = generate_learning_warnings(metrics, rolling, trend_status, market_status)

    state_frame = strategies.copy() if not strategies.empty else pd.DataFrame(columns=["strategy_state"])
    state_series = state_frame.get("strategy_state", pd.Series(dtype=str)).astype(str).str.lower()
    state_counts = {state: int((state_series == state).sum()) for state in ["active", "candidate", "probation", "disabled", "archived"]}

    best_symbol = pd.DataFrame(columns=["symbol"])
    if not strategies.empty:
        rank = strategies.copy()
        rank["combined_score"] = pd.to_numeric(rank.get("combined_score"), errors="coerce").fillna(0.0)
        rank["trade_count"] = pd.to_numeric(rank.get("trade_count", rank.get("sample_size")), errors="coerce").fillna(0).astype(int)
        rank["learning_confidence"] = pd.to_numeric(rank.get("learning_confidence"), errors="coerce").fillna(0.0)
        rank["recent_score"] = pd.to_numeric(rank.get("recent_score"), errors="coerce").fillna(0.0)
        rank["historical_score"] = pd.to_numeric(rank.get("historical_score"), errors="coerce").fillna(0.0)
        rank["trend_status"] = rank["recent_score"].sub(rank["historical_score"]).map(lambda d: "improving" if d > 0.03 else ("degrading" if d < -0.05 else "stable"))
        best_symbol = (
            rank.sort_values(["symbol", "combined_score"], ascending=[True, False])
            .groupby("symbol", as_index=False)
            .head(1)[["symbol", "strategy_name", "historical_score", "recent_score", "combined_score", "strategy_state", "trade_count", "learning_confidence", "trend_status"]]
            .rename(columns={"strategy_name": "best_strategy", "strategy_state": "lifecycle_state"})
            .reset_index(drop=True)
        )

    recent_changes = {
        "promoted_strategies": int(((state_changes.get("event_type", pd.Series(dtype=str)).astype(str) == "promotion")).sum()),
        "demoted_strategies": int(((state_changes.get("event_type", pd.Series(dtype=str)).astype(str) == "demotion")).sum()),
        "disabled_strategies": int((state_changes.get("new_state", pd.Series(dtype=str)).astype(str).str.lower() == "disabled").sum()),
        "moved_to_probation": int((state_changes.get("new_state", pd.Series(dtype=str)).astype(str).str.lower() == "probation").sum()),
        "best_params_changed": int(events.get("message", pd.Series(dtype=str)).astype(str).str.contains("best params", case=False).sum()),
        "optimizer_improvements": int(events.get("message", pd.Series(dtype=str)).astype(str).str.contains("optimizer completed", case=False).sum()),
    }

    return {
        "summary_metrics": metrics,
        "rolling_performance": rolling,
        "trend_status": trend_status,
        "trend_reason": trend_reason,
        "learning_health": "healthy" if trend_status in {"stable", "improving"} else ("waiting" if trend_status in {"insufficient_data", "market_closed_waiting"} else "needs_attention"),
        "warnings": warnings,
        "best_strategy_per_symbol": best_symbol,
        "strategy_state_counts": state_counts,
        "evidence_quality": {
            "historical_evidence_quality": historical_quality,
            "forward_evidence_quality": forward_quality,
            "combined_evidence_quality": combined_quality,
            "sample_sufficiency": sample_sufficiency,
            "confidence_basis": evidence_basis,
        },
        "recent_learning_changes": recent_changes,
        "readiness": {"status": readiness, "reason": readiness_reason},
    }
