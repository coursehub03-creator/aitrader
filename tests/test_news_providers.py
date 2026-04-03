from datetime import datetime, timedelta

import requests

from news.forexfactory_provider import ForexFactoryProvider
from news.providers import build_news_provider
from news.symbols import currencies_for_symbol


def test_provider_factory_returns_noop_for_unknown_provider() -> None:
    settings = {"news": {"provider": "unknown"}}
    provider = build_news_provider(settings)
    events = provider.fetch_events(datetime.utcnow(), datetime.utcnow())
    assert events == []


def test_symbol_currency_mapping_uses_fallback_split() -> None:
    symbol_map = {"GBPUSD": ["GBP", "USD"]}
    assert currencies_for_symbol("EURUSD", symbol_map) == ["EUR", "USD"]
    assert currencies_for_symbol("GBPUSD", symbol_map) == ["GBP", "USD"]


def test_forexfactory_provider_returns_empty_on_request_error(monkeypatch) -> None:
    provider = ForexFactoryProvider(endpoint="https://example.com/fail")

    def _boom(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise requests.RequestException("network down")

    monkeypatch.setattr("news.forexfactory_provider.requests.get", _boom)
    events = provider.fetch_events(datetime.utcnow() - timedelta(hours=1), datetime.utcnow() + timedelta(hours=1))
    assert events == []
