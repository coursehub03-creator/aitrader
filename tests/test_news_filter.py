from datetime import datetime, timedelta

from core.types import NewsEvent
from news.filter import NewsFilter


def test_news_filter_blocks() -> None:
    now = datetime.utcnow()
    events = [NewsEvent("NFP", "USD", "High", now + timedelta(minutes=10), "test")]
    blocked, reason = NewsFilter(30, 30).should_block(now, events, ["USD", "EUR"])
    assert blocked is True
    assert "High-impact" in reason
