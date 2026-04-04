"""Alert qualification, cooldown, duplicate suppression, and persistence helpers."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core.types import FinalRecommendation, SignalAction


@dataclass(slots=True)
class AlertDecision:
    should_alert: bool
    sent: bool
    status: str
    reason: str
    key: str


@dataclass(slots=True)
class AlertRecord:
    symbol: str
    timeframe: str
    action: str
    signal_strength: str
    confidence: float
    risk_reward: float
    entry: float
    stop_loss: float
    take_profit: float
    fingerprint: str
    timestamp: str


SIGNAL_STRENGTH_RANK = {"weak": 0, "medium": 1, "strong": 2}


class AlertCooldownStore:
    """Stores cooldown markers per symbol, timeframe, and direction."""

    def __init__(self, state_path: Path, cooldown_seconds: int = 900) -> None:
        self.state_path = state_path
        self.cooldown_seconds = max(1, int(cooldown_seconds))
        self._state: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if not self.state_path.exists():
            return
        try:
            self._state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            self._state = {}

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self._state), encoding="utf-8")

    @staticmethod
    def build_key(recommendation: FinalRecommendation) -> str:
        action = recommendation.action.value if hasattr(recommendation.action, "value") else recommendation.action
        return f"{recommendation.symbol}:{recommendation.timeframe}:{action}"

    def can_send(self, key: str, now: datetime) -> tuple[bool, str]:
        timestamp_raw = self._state.get(key)
        if not timestamp_raw:
            return True, "cooldown_clear"
        last_sent = datetime.fromisoformat(timestamp_raw)
        if (now - last_sent) >= timedelta(seconds=self.cooldown_seconds):
            return True, "cooldown_elapsed"
        return False, "duplicate_suppressed_by_cooldown"

    def mark_sent(self, key: str, now: datetime) -> None:
        self._state[key] = now.replace(tzinfo=timezone.utc).isoformat()
        self._save()


class AlertHistoryStore:
    """Appends alert records and suppresses near-identical duplicates."""

    def __init__(self, history_path: Path, duplicate_window_seconds: int = 1800) -> None:
        self.history_path = history_path
        self.duplicate_window_seconds = max(1, int(duplicate_window_seconds))

    @staticmethod
    def _normalize_action(action: Any) -> str:
        return str(getattr(action, "value", action)).upper()

    @classmethod
    def build_fingerprint(cls, recommendation: FinalRecommendation) -> str:
        action = cls._normalize_action(recommendation.action)
        return "|".join(
            [
                recommendation.symbol.upper(),
                recommendation.timeframe.upper(),
                action,
                str(recommendation.signal_strength).lower(),
                f"{float(recommendation.entry):.5f}",
                f"{float(recommendation.stop_loss):.5f}",
                f"{float(recommendation.take_profit):.5f}",
                f"{float(recommendation.confidence):.3f}",
                f"{float(recommendation.risk_reward):.2f}",
            ]
        )

    def _iter_records(self) -> list[dict[str, Any]]:
        if not self.history_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        try:
            with self.history_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        raw = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(raw, dict):
                        rows.append(raw)
        except OSError:
            return []
        return rows

    def suppress_duplicate(self, recommendation: FinalRecommendation, now: datetime) -> tuple[bool, str, str]:
        fingerprint = self.build_fingerprint(recommendation)
        rows = self._iter_records()
        for row in reversed(rows):
            if str(row.get("fingerprint", "")) != fingerprint:
                continue
            ts_raw = row.get("timestamp")
            if not ts_raw:
                continue
            try:
                last_seen = datetime.fromisoformat(str(ts_raw))
            except ValueError:
                continue
            if (now - last_seen) < timedelta(seconds=self.duplicate_window_seconds):
                return False, "duplicate_suppressed_by_history", fingerprint
            break
        return True, "history_clear", fingerprint

    def mark_sent(self, recommendation: FinalRecommendation, now: datetime) -> None:
        fingerprint = self.build_fingerprint(recommendation)
        record = AlertRecord(
            symbol=recommendation.symbol.upper(),
            timeframe=recommendation.timeframe.upper(),
            action=self._normalize_action(recommendation.action),
            signal_strength=str(recommendation.signal_strength),
            confidence=float(recommendation.confidence),
            risk_reward=float(recommendation.risk_reward),
            entry=float(recommendation.entry),
            stop_loss=float(recommendation.stop_loss),
            take_profit=float(recommendation.take_profit),
            fingerprint=fingerprint,
            timestamp=now.replace(tzinfo=timezone.utc).isoformat(timespec="seconds"),
        )
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        with self.history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(record)) + "\n")


class AlertPolicy:
    """Encapsulates strong-opportunity alert qualification rules."""

    def __init__(
        self,
        min_confidence: float,
        min_risk_reward: float,
        min_signal_strength: str = "strong",
        min_quality_score: float = 0.72,
        strategy_weight: float = 0.2,
        recent_performance_weight: float = 0.15,
    ) -> None:
        self.min_confidence = float(min_confidence)
        self.min_risk_reward = float(min_risk_reward)
        self.min_signal_strength = str(min_signal_strength).lower()
        self.min_quality_score = float(min_quality_score)
        self.strategy_weight = float(strategy_weight)
        self.recent_performance_weight = float(recent_performance_weight)

    @staticmethod
    def _clamp01(value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    def compute_quality_score(self, recommendation: FinalRecommendation) -> float:
        confidence_component = self._clamp01(float(recommendation.confidence))
        risk_reward_component = self._clamp01(float(recommendation.risk_reward) / max(1.0, self.min_risk_reward))
        strategy_raw = getattr(recommendation, "strategy_score", None)
        strategy_component = self._clamp01(float(strategy_raw) / 10.0) if strategy_raw is not None else 0.5
        recent_raw = getattr(recommendation, "recent_performance_score", None)
        recent_component = self._clamp01(float(recent_raw)) if recent_raw is not None else 0.5
        base_weight = max(0.0, 1.0 - self.strategy_weight - self.recent_performance_weight)
        quality_score = (
            (base_weight * 0.5 * confidence_component)
            + (base_weight * 0.5 * risk_reward_component)
            + (self.strategy_weight * strategy_component)
            + (self.recent_performance_weight * recent_component)
        )
        return self._clamp01(quality_score)

    def qualifies(self, recommendation: FinalRecommendation) -> tuple[bool, str]:
        action = recommendation.action.value if hasattr(recommendation.action, "value") else recommendation.action
        if recommendation.market_status != "open":
            return False, "market_closed_or_unavailable"
        if recommendation.news_status == "blocked":
            return False, "news_blocked"
        if str(getattr(recommendation, "spread_state", "unknown")).lower() == "excessive":
            return False, "spread_excessive"
        if action not in {SignalAction.BUY, SignalAction.SELL, "BUY", "SELL"}:
            return False, "not_actionable"
        required_strength = SIGNAL_STRENGTH_RANK.get(self.min_signal_strength, SIGNAL_STRENGTH_RANK["strong"])
        current_strength = SIGNAL_STRENGTH_RANK.get(str(recommendation.signal_strength).lower(), 0)
        if current_strength < required_strength:
            return False, "weak_or_medium_signal"
        if float(recommendation.confidence) < self.min_confidence:
            return False, "confidence_below_threshold"
        if float(recommendation.risk_reward) < self.min_risk_reward:
            return False, "risk_reward_below_threshold"
        quality_score = self.compute_quality_score(recommendation)
        recommendation.alert_quality_score = quality_score
        if quality_score < self.min_quality_score:
            return False, "quality_score_below_threshold"
        return True, "qualified"
