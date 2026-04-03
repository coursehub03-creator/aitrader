"""Alert qualification, cooldown, and persistence helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.types import FinalRecommendation, SignalAction


@dataclass(slots=True)
class AlertDecision:
    should_alert: bool
    sent: bool
    status: str
    reason: str
    key: str


class AlertCooldownStore:
    """Stores cooldown markers per symbol and direction."""

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
        return f"{recommendation.symbol}:{action}"

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


class AlertPolicy:
    """Encapsulates strong-opportunity alert qualification rules."""

    def __init__(self, min_confidence: float, min_risk_reward: float) -> None:
        self.min_confidence = float(min_confidence)
        self.min_risk_reward = float(min_risk_reward)

    def qualifies(self, recommendation: FinalRecommendation) -> tuple[bool, str]:
        action = recommendation.action.value if hasattr(recommendation.action, "value") else recommendation.action
        if recommendation.market_status != "open":
            return False, "market_closed_or_unavailable"
        if recommendation.news_status == "blocked":
            return False, "news_blocked"
        if action not in {SignalAction.BUY, SignalAction.SELL, "BUY", "SELL"}:
            return False, "not_actionable"
        if recommendation.signal_strength != "strong":
            return False, "weak_or_medium_signal"
        if float(recommendation.confidence) < self.min_confidence:
            return False, "confidence_below_threshold"
        if float(recommendation.risk_reward) < self.min_risk_reward:
            return False, "risk_reward_below_threshold"
        return True, "qualified"
