"""Unified historical + forward-learning scoring and lifecycle logic."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class CombinedScore:
    historical_score: float
    recent_score: float
    combined_score: float


@dataclass(slots=True)
class LifecycleDecision:
    lifecycle_state: str
    promotion_allowed: bool
    demotion_triggered: bool
    reasons: list[str]


class UnifiedLearningScorer:
    def __init__(
        self,
        historical_weight: float = 0.4,
        recent_weight: float = 0.6,
        min_sample_size: int = 15,
        max_drawdown: float = 7.5,
        min_expectancy: float = 0.0,
        degradation_threshold: float = 25.0,
        min_recent_score: float = 0.0,
    ) -> None:
        total_weight = float(historical_weight) + float(recent_weight)
        if total_weight <= 0:
            raise ValueError("Historical/recent weights must sum to a positive value.")
        self.historical_weight = float(historical_weight) / total_weight
        self.recent_weight = float(recent_weight) / total_weight
        self.min_sample_size = min_sample_size
        self.max_drawdown = max_drawdown
        self.min_expectancy = min_expectancy
        self.degradation_threshold = degradation_threshold
        self.min_recent_score = min_recent_score

    def score(self, historical_score: float, recent_score: float) -> CombinedScore:
        combined = (historical_score * self.historical_weight) + (recent_score * self.recent_weight)
        return CombinedScore(
            historical_score=float(historical_score),
            recent_score=float(recent_score),
            combined_score=float(combined),
        )

    def evaluate(
        self,
        *,
        sample_size: int,
        recent_drawdown: float,
        expectancy: float,
        historical_score: float,
        recent_score: float,
        previous_state: str = "candidate",
    ) -> LifecycleDecision:
        normalized_previous = str(previous_state).strip().lower() or "candidate"
        reasons: list[str] = []

        has_sample = int(sample_size) >= self.min_sample_size
        healthy_expectancy = float(expectancy) >= self.min_expectancy
        drawdown_within_limit = float(recent_drawdown) <= self.max_drawdown
        degradation = float(historical_score) - float(recent_score)
        degraded = degradation > self.degradation_threshold
        recent_viable = float(recent_score) >= self.min_recent_score and not degraded

        if not has_sample:
            reasons.append(f"Insufficient historical sample ({sample_size} < {self.min_sample_size}).")
        if not healthy_expectancy:
            reasons.append(f"Expectancy below limit ({expectancy:.4f} < {self.min_expectancy:.4f}).")
        if not drawdown_within_limit:
            reasons.append(f"Drawdown above limit ({recent_drawdown:.2f} > {self.max_drawdown:.2f}).")
        if float(recent_score) < self.min_recent_score:
            reasons.append(f"Recent paper score below viability floor ({recent_score:.2f} < {self.min_recent_score:.2f}).")
        if degraded:
            reasons.append(
                f"Recent paper performance degraded by {degradation:.2f} points (threshold {self.degradation_threshold:.2f})."
            )

        if normalized_previous == "archived":
            return LifecycleDecision(
                lifecycle_state="archived",
                promotion_allowed=False,
                demotion_triggered=False,
                reasons=["Strategy remains archived until manually reactivated."],
            )
        if not has_sample:
            return LifecycleDecision(
                lifecycle_state="candidate",
                promotion_allowed=False,
                demotion_triggered=False,
                reasons=reasons or ["Awaiting sufficient validation sample."],
            )
        if not healthy_expectancy or not drawdown_within_limit:
            return LifecycleDecision(
                lifecycle_state="disabled",
                promotion_allowed=False,
                demotion_triggered=normalized_previous in {"active", "probation"},
                reasons=reasons or ["Risk/expectancy limits failed."],
            )
        if degraded:
            return LifecycleDecision(
                lifecycle_state="probation",
                promotion_allowed=False,
                demotion_triggered=normalized_previous == "active",
                reasons=reasons,
            )
        return LifecycleDecision(
            lifecycle_state="active",
            promotion_allowed=has_sample and recent_viable and healthy_expectancy and drawdown_within_limit,
            demotion_triggered=False,
            reasons=["Promotion criteria satisfied by historical + recent paper performance."],
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
        return self.evaluate(
            sample_size=sample_size,
            recent_drawdown=recent_drawdown,
            expectancy=expectancy,
            historical_score=historical_score,
            recent_score=recent_score,
            previous_state=previous_state,
        ).lifecycle_state

    def promote_allowed(
        self,
        *,
        sample_size: int,
        recent_drawdown: float,
        expectancy: float,
        historical_score: float = 0.0,
        recent_score: float | None = None,
    ) -> bool:
        return self.evaluate(
            sample_size=sample_size,
            recent_drawdown=recent_drawdown,
            expectancy=expectancy,
            historical_score=historical_score,
            recent_score=max(self.min_recent_score, 0.0) if recent_score is None else float(recent_score),
            previous_state="candidate",
        ).promotion_allowed
