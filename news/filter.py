"""News filtering around high-impact windows."""

from __future__ import annotations

from datetime import datetime, timedelta

from core.types import NewsEvent


class NewsFilter:
    def __init__(self, before_minutes: int, after_minutes: int) -> None:
        self.before = timedelta(minutes=before_minutes)
        self.after = timedelta(minutes=after_minutes)

    def should_block(self, now: datetime, events: list[NewsEvent], symbol_currencies: list[str]) -> tuple[bool, str]:
        for event in events:
            if event.currency not in symbol_currencies:
                continue
            if event.impact.lower() not in {"high", "red"}:
                continue
            if event.event_time - self.before <= now <= event.event_time + self.after:
                return True, f"High-impact news window: {event.title} ({event.currency})"
        return False, "No high-impact blocking events"
