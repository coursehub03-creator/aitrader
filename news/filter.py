"""News filtering around high-impact windows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from core.types import NewsEvent


@dataclass(slots=True)
class NewsFilterDecision:
    decision: str
    reason: str
    confidence_multiplier: float


class NewsFilter:
    def __init__(
        self,
        before_minutes: int,
        after_minutes: int,
        medium_impact_confidence_multiplier: float = 0.7,
    ) -> None:
        self.before = timedelta(minutes=before_minutes)
        self.after = timedelta(minutes=after_minutes)
        self.medium_multiplier = float(medium_impact_confidence_multiplier)
        self.major_macro_currencies = {"USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD"}

    def evaluate(
        self,
        now: datetime,
        events: list[NewsEvent],
        symbol_currencies: list[str],
    ) -> NewsFilterDecision:
        watched = {currency.upper() for currency in symbol_currencies}
        include_major_macro = "MACRO" in watched
        for event in events:
            event_currency = event.currency.upper()
            if event_currency not in watched and not (include_major_macro and event_currency in self.major_macro_currencies):
                continue
            if not (event.event_time - self.before <= now <= event.event_time + self.after):
                continue

            impact = event.impact.lower()
            if impact in {"high", "red"}:
                return NewsFilterDecision(
                    decision="block trading",
                    reason=f"High-impact news window: {event.title} ({event.currency})",
                    confidence_multiplier=0.0,
                )
            if impact in {"medium", "med", "orange"}:
                return NewsFilterDecision(
                    decision="reduce confidence",
                    reason=f"Medium-impact news nearby: {event.title} ({event.currency})",
                    confidence_multiplier=self.medium_multiplier,
                )

        return NewsFilterDecision(
            decision="allow trading",
            reason="No relevant blocking events",
            confidence_multiplier=1.0,
        )

    def should_block(
        self,
        now: datetime,
        events: list[NewsEvent],
        symbol_currencies: list[str],
    ) -> tuple[bool, str]:
        decision = self.evaluate(now, events, symbol_currencies)
        return decision.decision == "block trading", decision.reason
