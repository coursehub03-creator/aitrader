from __future__ import annotations

from learning.unified import UnifiedLearningScorer


def test_combined_score_weighting() -> None:
    scorer = UnifiedLearningScorer(historical_weight=0.3, recent_weight=0.7)
    combined = scorer.score(40.0, 80.0)

    assert combined.historical_score == 40.0
    assert combined.recent_score == 80.0
    assert combined.combined_score == 68.0


def test_lifecycle_transitions_candidate_probation_disabled_active() -> None:
    scorer = UnifiedLearningScorer(min_sample_size=10, max_drawdown=5.0, min_expectancy=0.0, degradation_threshold=20.0)

    assert (
        scorer.lifecycle_state(
            sample_size=3,
            recent_drawdown=1.0,
            expectancy=0.3,
            historical_score=70.0,
            recent_score=60.0,
        )
        == "candidate"
    )

    assert (
        scorer.lifecycle_state(
            sample_size=20,
            recent_drawdown=2.0,
            expectancy=0.5,
            historical_score=90.0,
            recent_score=50.0,
        )
        == "probation"
    )

    assert (
        scorer.lifecycle_state(
            sample_size=20,
            recent_drawdown=7.0,
            expectancy=-0.1,
            historical_score=90.0,
            recent_score=85.0,
        )
        == "disabled"
    )

    assert (
        scorer.lifecycle_state(
            sample_size=20,
            recent_drawdown=2.0,
            expectancy=0.2,
            historical_score=75.0,
            recent_score=70.0,
        )
        == "active"
    )
