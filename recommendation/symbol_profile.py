"""Per-symbol profile helpers for recommendation tuning."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class SymbolProfile:
    name: str
    preferred_timeframes: list[str] = field(default_factory=list)
    min_confidence: float = 0.6
    min_risk_reward: float = 1.5
    atr_low_threshold: float = 0.0005
    atr_high_threshold: float = 0.005
    atr_extreme_threshold: float = 0.0075
    spread_threshold: float = 25.0
    spread_elevated_ratio: float = 0.75
    preferred_sessions: list[str] = field(default_factory=list)
    session_outside_policy: str = "reduce"
    session_confidence_multiplier: float = 0.8
    news_sensitivity: dict[str, Any] = field(default_factory=dict)
    optimizer_ranges: dict[str, dict[str, list[Any]]] = field(default_factory=dict)

    def to_display_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "preferred_timeframes": list(self.preferred_timeframes),
            "preferred_sessions": list(self.preferred_sessions),
            "session_outside_policy": self.session_outside_policy,
            "session_confidence_multiplier": float(self.session_confidence_multiplier),
            "spread_threshold": float(self.spread_threshold),
            "spread_elevated_ratio": float(self.spread_elevated_ratio),
            "atr_low_threshold": float(self.atr_low_threshold),
            "atr_high_threshold": float(self.atr_high_threshold),
            "atr_extreme_threshold": float(self.atr_extreme_threshold),
            "min_confidence": float(self.min_confidence),
            "min_risk_reward": float(self.min_risk_reward),
            "news_sensitivity": dict(self.news_sensitivity),
            "optimizer_ranges": dict(self.optimizer_ranges),
        }


def session_state(now_utc: datetime) -> str:
    hour = now_utc.hour
    if 7 <= hour < 9:
        return "asian_london_overlap"
    if 13 <= hour < 16:
        return "london_newyork_overlap"
    if 0 <= hour < 8:
        return "asian"
    if 7 <= hour < 16:
        return "london"
    if 13 <= hour < 22:
        return "new_york"
    return "off_session"


def profile_for_symbol(symbol: str, settings: Any) -> SymbolProfile:
    symbol_key = symbol.upper()
    profiles = settings.get("recommendation.symbol_profiles", {}) if hasattr(settings, "get") else {}
    default_profile = profiles.get("DEFAULT", {}) if isinstance(profiles, dict) else {}
    specific = profiles.get(symbol_key, {}) if isinstance(profiles, dict) else {}
    merged = {**default_profile, **specific}

    return SymbolProfile(
        name=specific.get("name", symbol_key) if isinstance(specific, dict) else symbol_key,
        preferred_timeframes=list(merged.get("preferred_timeframes", [])),
        min_confidence=float(merged.get("min_confidence", settings.get("recommendation.min_confidence", 0.6))),
        min_risk_reward=float(merged.get("min_risk_reward", settings.get("recommendation.min_risk_reward", 1.5))),
        atr_low_threshold=float(merged.get("atr_low_threshold", settings.get("recommendation.volatility.low_atr_pct", 0.0005))),
        atr_high_threshold=float(merged.get("atr_high_threshold", settings.get("recommendation.volatility.high_atr_pct", 0.005))),
        atr_extreme_threshold=float(
            merged.get("atr_extreme_threshold", settings.get("recommendation.volatility.extreme_high_atr_pct", 0.0075))
        ),
        spread_threshold=float(merged.get("spread_threshold", settings.get("recommendation.spread.default_threshold", 25.0))),
        spread_elevated_ratio=float(merged.get("spread_elevated_ratio", settings.get("recommendation.spread.elevated_ratio", 0.75))),
        preferred_sessions=[str(item).lower() for item in merged.get("preferred_sessions", [])],
        session_outside_policy=str(merged.get("session_outside_policy", "reduce")).lower(),
        session_confidence_multiplier=float(merged.get("session_confidence_multiplier", 0.8)),
        news_sensitivity=dict(merged.get("news_sensitivity", {})),
        optimizer_ranges=dict(merged.get("optimizer_ranges", {})),
    )
