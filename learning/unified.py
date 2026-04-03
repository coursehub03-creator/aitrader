"""Unified historical + forward-learning scoring and lifecycle logic."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class CombinedScore:
    historical_score: float
    recent_score: float
    combined_score: float


class UnifiedLearningScorer:
    def __init__(
        self,
        historical_weight: float = 0.4,
        recent_weight: float = 0.6,
        min_sample_size: int = 15,
        max_drawdown: float = 7.5,
        min_expectancy: float = 0.0,
        degradation_threshold: float = 25.0,
    ) -> None:
        self.historical_weight = historical_weight
        self.recent_weight = recent_weight
        self.min_sample_size = min_sample_size
        self.max_drawdown = max_drawdown
        self.min_expectancy = min_expectancy
        self.degradation_threshold = degradation_threshold

    def score(self, historical_score: float, recent_score: float) -> CombinedScore:
        combined = (historical_score * self.historical_weight) + (recent_score * self.recent_weight)
        return CombinedScore(
            historical_score=float(historical_score),
            recent_score=float(recent_score),
            combined_score=float(combined),
        )

    def lifecycle_state(
        self,
        *,
        sample_size: int,
        recent_drawdown: float,
        expectancy: float,
        historical_score: float,
        recent_score: float,
        previous_state: str = "candidate",
    ) -> str:
        if sample_size < self.min_sample_size:
            return "candidate"
        if recent_drawdown > self.max_drawdown or expectancy < self.min_expectancy:
            return "disabled"
        if (historical_score - recent_score) > self.degradation_threshold:
            return "probation"
        if previous_state == "archived":
            return "archived"
        return "active"

    def promote_allowed(self, *, sample_size: int, recent_drawdown: float, expectancy: float) -> bool:
        return (
            sample_size >= self.min_sample_size
            and recent_drawdown <= self.max_drawdown
            and expectancy >= self.min_expectancy
        )
