"""ForexFactory-compatible provider (safe, swappable)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

from core.types import NewsEvent
from news.base import NewsProvider

LOGGER = logging.getLogger(__name__)


class ForexFactoryProvider(NewsProvider):
    def __init__(self, endpoint: str, timeout: int = 10) -> None:
        self.endpoint = endpoint
        self.timeout = timeout

    def fetch_events(self, from_time: datetime, to_time: datetime) -> list[NewsEvent]:
        if not self.endpoint:
            return []
        try:
            response = requests.get(self.endpoint, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            LOGGER.warning("News provider fetch failed, continuing with empty events: %s", exc)
            return []

        events: list[NewsEvent] = []
        for item in payload:
            event_time = self._parse_time(item)
            if event_time is None or not (from_time <= event_time <= to_time):
                continue
            events.append(
                NewsEvent(
                    title=item.get("title", "Unknown"),
                    currency=item.get("currency", item.get("country", "UNK")),
                    impact=item.get("impact", "Low"),
                    event_time=event_time,
                    source="ForexFactory",
                )
            )
        return events

    @staticmethod
    def _parse_time(item: dict) -> datetime | None:
        if "date" in item and "T" in str(item["date"]):
            try:
                return (
                    datetime.fromisoformat(str(item["date"]).replace("Z", "+00:00"))
                    .astimezone(timezone.utc)
                    .replace(tzinfo=None)
                )
            except Exception:
                return None
        return None
