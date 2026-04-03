"""ForexFactory-compatible provider (safe and swappable)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import requests

from core.types import NewsEvent
from news.base import NewsProvider

LOGGER = logging.getLogger(__name__)


class ForexFactoryProvider(NewsProvider):
    """Fetches events from a JSON endpoint compatible with ForexFactory feeds."""

    def __init__(self, endpoint: str, timeout: int = 10) -> None:
        self.endpoint = endpoint
        self.timeout = timeout

    def fetch_events(self, from_time: datetime, to_time: datetime) -> list[NewsEvent]:
        if not self.endpoint:
            LOGGER.warning("News endpoint is empty; running without news events.")
            return []

        try:
            response = requests.get(self.endpoint, timeout=self.timeout)
            response.raise_for_status()
            payload: Any = response.json()
        except requests.RequestException as exc:
            LOGGER.warning("News request failed for '%s': %s", self.endpoint, exc)
            return []
        except ValueError as exc:
            LOGGER.warning("News endpoint returned invalid JSON for '%s': %s", self.endpoint, exc)
            return []

        if not isinstance(payload, list):
            LOGGER.warning("Unexpected news payload type: %s. Expected list.", type(payload).__name__)
            return []

        events: list[NewsEvent] = []
        for item in payload:
            if not isinstance(item, dict):
                continue

            event_time = self._parse_time(item)
            if event_time is None or not (from_time <= event_time <= to_time):
                continue

            events.append(
                NewsEvent(
                    title=str(item.get("title", "Unknown")),
                    currency=str(item.get("currency", item.get("country", "UNK"))),
                    impact=str(item.get("impact", "Low")),
                    event_time=event_time,
                    source="ForexFactory",
                )
            )

        return events

    @staticmethod
    def _parse_time(item: dict[str, Any]) -> datetime | None:
        date_value = item.get("date")
        time_value = item.get("time")

        if isinstance(date_value, str) and "T" in date_value:
            try:
                return (
                    datetime.fromisoformat(date_value.replace("Z", "+00:00"))
                    .astimezone(timezone.utc)
                    .replace(tzinfo=None)
                )
            except ValueError:
                return None

        if isinstance(date_value, str) and isinstance(time_value, str):
            candidate = (
                f"{date_value}T{time_value}:00"
                if len(time_value) == 5
                else f"{date_value}T{time_value}"
            )
            try:
                return datetime.fromisoformat(candidate)
            except ValueError:
                return None

        return None