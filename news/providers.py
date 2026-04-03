"""News provider construction with pluggable provider registry."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable

from core.types import NewsEvent
from news.base import NewsProvider
from news.forexfactory_provider import ForexFactoryProvider

LOGGER = logging.getLogger(__name__)


class NullNewsProvider(NewsProvider):
    def fetch_events(self, from_time: datetime, to_time: datetime) -> list[NewsEvent]:
        return []


def build_news_provider(settings: Any) -> NewsProvider:
    provider_name = str(_get_setting(settings, "news.provider", "forexfactory")).lower()

    registry: dict[str, Callable[[], NewsProvider]] = {
        "forexfactory": lambda: ForexFactoryProvider(
            endpoint=str(_get_setting(settings, "news.endpoint", "")),
            timeout=int(_get_setting(settings, "news.timeout_sec", 10)),
        ),
        "none": NullNewsProvider,
    }

    factory = registry.get(provider_name)
    if factory is None:
        LOGGER.warning("Unknown news provider '%s'; defaulting to no-op provider.", provider_name)
        return NullNewsProvider()

    return factory()


def _get_setting(settings: Any, key: str, default: Any) -> Any:
    value = settings.get(key, default)
    if value is not default:
        return value

    node: Any = settings
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node
