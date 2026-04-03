"""Reusable monitor-loop state helpers for CLI/UI watch modes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(slots=True)
class MonitorState:
    """Lightweight monitor runtime state for stable refresh loops."""

    is_running: bool = False
    interval_seconds: int = 15
    last_refresh_at: datetime | None = None
    next_refresh_at: datetime | None = None
    last_alert_at: datetime | None = None
    last_alert_status: str = "n/a"

    def start(self, now: datetime | None = None) -> None:
        current = now or datetime.now(tz=timezone.utc)
        self.is_running = True
        self.next_refresh_at = current

    def stop(self) -> None:
        self.is_running = False
        self.next_refresh_at = None

    def should_run_cycle(self, now: datetime | None = None) -> bool:
        if not self.is_running:
            return False
        current = now or datetime.now(tz=timezone.utc)
        if self.next_refresh_at is None:
            self.next_refresh_at = current
        return current >= self.next_refresh_at

    def mark_cycle_complete(self, *, now: datetime | None = None, interval_seconds: int | None = None) -> None:
        current = now or datetime.now(tz=timezone.utc)
        if interval_seconds is not None:
            self.interval_seconds = max(3, int(interval_seconds))
        self.last_refresh_at = current
        self.next_refresh_at = current + timedelta(seconds=self.interval_seconds)

    def mark_alert(self, *, status: str, now: datetime | None = None) -> None:
        self.last_alert_status = status
        if status == "sent":
            self.last_alert_at = now or datetime.now(tz=timezone.utc)


def to_utc_label(value: datetime | None) -> str:
    """Convert UTC timestamp to UI-friendly string."""
    if value is None:
        return "Never"
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

