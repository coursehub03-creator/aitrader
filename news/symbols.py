"""Symbol-to-currency relevance helpers for news filtering."""

from __future__ import annotations


def currencies_for_symbol(symbol: str, symbols_map: dict[str, list[str]]) -> list[str]:
    normalized_symbol = symbol.upper()
    configured = symbols_map.get(normalized_symbol, [])
    if configured:
        return [currency.upper() for currency in configured]

    if len(normalized_symbol) >= 6 and normalized_symbol.isalpha():
        return [normalized_symbol[:3], normalized_symbol[3:6]]

    return []
