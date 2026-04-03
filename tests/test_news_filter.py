from datetime import datetime, timedelta

from core.types import NewsEvent
from news.filter import NewsFilter


def test_news_filter_blocks() -> None:
    now = datetime.utcnow()
    events = [
        NewsEvent(
            event_id="1",
            title="NFP",
            currency="USD",
            impact="High",
            event_time=now + timedelta(minutes=10),
            actual=None,
            forecast=None,
            previous=None,
            source="test",
        )
    ]
    decision = NewsFilter(30, 30).evaluate(now, events, ["USD", "EUR"])
    assert decision.decision == "block trading"
    assert decision.confidence_multiplier == 0.0
    assert "High-impact" in decision.reason


def test_news_filter_reduces_confidence_for_medium_impact() -> None:
    now = datetime.utcnow()
    events = [
        NewsEvent(
            event_id="2",
            title="PMI",
            currency="EUR",
            impact="Medium",
            event_time=now + timedelta(minutes=5),
            actual=None,
            forecast=None,
            previous=None,
            source="test",
        )
    ]
    decision = NewsFilter(30, 30).evaluate(now, events, ["EUR", "USD"])
    assert decision.decision == "reduce confidence"
    assert decision.confidence_multiplier < 1.0
    assert "Medium-impact" in decision.reason
