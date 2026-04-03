from __future__ import annotations

from datetime import datetime, timedelta, timezone

from monitoring.live_monitor import MonitorState, to_utc_label


def test_monitor_state_runs_only_when_due() -> None:
    state = MonitorState(is_running=False, interval_seconds=10)
    now = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)
    state.start(now)
    assert state.should_run_cycle(now) is True

    state.mark_cycle_complete(now=now, interval_seconds=10)
    assert state.should_run_cycle(now + timedelta(seconds=9)) is False
    assert state.should_run_cycle(now + timedelta(seconds=10)) is True


def test_monitor_state_tracks_last_alert_for_sent_only() -> None:
    state = MonitorState(is_running=True, interval_seconds=10)
    now = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)
    state.mark_alert(status="suppressed", now=now)
    assert state.last_alert_at is None

    state.mark_alert(status="sent", now=now)
    assert state.last_alert_at == now
    assert to_utc_label(state.last_alert_at).endswith("UTC")

