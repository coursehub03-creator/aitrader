"""News provider abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from core.types import NewsEvent


class NewsProvider(ABC):
    @abstractmethod
    def fetch_events(self, from_time: datetime, to_time: datetime) -> list[NewsEvent]:
        """Fetch events in [from_time, to_time]."""
