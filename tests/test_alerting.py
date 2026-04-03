from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.types import FinalRecommendation, SignalAction
from monitoring.alerts import AlertCooldownStore, AlertHistoryStore, AlertPolicy
from notification.telegram_notifier import TelegramConfig, TelegramNotifier


def _recommendation(
    *,
    market_status: str = "open",
    news_status: str = "clear",
    action: SignalAction = SignalAction.BUY,
    strength: str = "strong",
    confidence: float = 0.8,
    risk_reward: float = 2.0,
) -> FinalRecommendation:
    return FinalRecommendation(
        symbol="EURUSD",
        timeframe="M5",
        action=action,
        market_price=1.1,
        entry=1.1,
        stop_loss=1.09,
        take_profit=1.12,
        risk_reward=risk_reward,
        confidence=confidence,
        selected_strategy="trend_rsi",
        market_status=market_status,
        news_status=news_status,
        signal_strength=strength,
        reasons=["trend aligned", "confluence strong"],
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_telegram_message_contains_required_fields() -> None:
    notifier = TelegramNotifier(TelegramConfig(enabled=True, bot_token="t", chat_id="c"))
    message = notifier.build_message(_recommendation())

    for required in [
        "Symbol",
        "Timeframe",
        "Action",
        "Entry",
        "Stop Loss",
        "Take Profit",
        "Confidence",
        "Signal Strength",
        "Selected Strategy",
        "Market Status",
        "News Status",
        "Spread State",
        "Session State",
        "Risk/Reward",
        "Reasons",
        "Timestamp",
    ]:
        assert required in message


def test_cooldown_logic_suppresses_duplicate_alerts(tmp_path) -> None:
    store = AlertCooldownStore(tmp_path / "state.json", cooldown_seconds=300)
    rec = _recommendation(action=SignalAction.BUY)
    key = store.build_key(rec)

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    can_send, _ = store.can_send(key, now)
    assert can_send is True

    store.mark_sent(key, now)
    can_send_again, reason = store.can_send(key, now + timedelta(seconds=60))
    assert can_send_again is False
    assert reason == "duplicate_suppressed_by_cooldown"
    assert key == "EURUSD:M5:BUY"


def test_cooldown_allows_after_expiry(tmp_path) -> None:
    store = AlertCooldownStore(tmp_path / "state.json", cooldown_seconds=300)
    rec = _recommendation(action=SignalAction.SELL)
    key = store.build_key(rec)

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    store.mark_sent(key, now)
    can_send, reason = store.can_send(key, now + timedelta(seconds=301))
    assert can_send is True
    assert reason == "cooldown_elapsed"


def test_duplicate_history_suppresses_identical_alerts(tmp_path) -> None:
    history = AlertHistoryStore(tmp_path / "sent.jsonl", duplicate_window_seconds=1200)
    rec = _recommendation(action=SignalAction.BUY)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    can_send, reason, _ = history.suppress_duplicate(rec, now)
    assert can_send is True
    assert reason == "history_clear"

    history.mark_sent(rec, now)
    can_send2, reason2, _ = history.suppress_duplicate(rec, now + timedelta(minutes=5))
    assert can_send2 is False
    assert reason2 == "duplicate_suppressed_by_history"


def test_duplicate_history_allows_after_window(tmp_path) -> None:
    history = AlertHistoryStore(tmp_path / "sent.jsonl", duplicate_window_seconds=60)
    rec = _recommendation(action=SignalAction.SELL)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    history.mark_sent(rec, now)

    can_send, reason, _ = history.suppress_duplicate(rec, now + timedelta(seconds=61))
    assert can_send is True
    assert reason == "history_clear"


def test_no_alert_when_market_closed() -> None:
    policy = AlertPolicy(min_confidence=0.6, min_risk_reward=1.5)
    qualifies, reason = policy.qualifies(_recommendation(market_status="closed"))

    assert qualifies is False
    assert reason == "market_closed_or_unavailable"


def test_no_alert_when_news_blocks_trading() -> None:
    policy = AlertPolicy(min_confidence=0.6, min_risk_reward=1.5)
    qualifies, reason = policy.qualifies(_recommendation(news_status="blocked"))

    assert qualifies is False
    assert reason == "news_blocked"


def test_no_alert_for_weak_signal() -> None:
    policy = AlertPolicy(min_confidence=0.6, min_risk_reward=1.5)
    qualifies, reason = policy.qualifies(_recommendation(strength="weak"))

    assert qualifies is False
    assert reason == "weak_or_medium_signal"


def test_safe_failure_when_telegram_not_configured() -> None:
    notifier = TelegramNotifier(TelegramConfig(enabled=True, bot_token="", chat_id=""))
    sent, reason = notifier.send_recommendation_alert(_recommendation())
    assert sent is False
    assert reason == "telegram_not_configured"


def test_telegram_from_settings_reads_environment(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_ENABLED", "1")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "env-chat")
    monkeypatch.setenv("TELEGRAM_TIMEOUT_SECONDS", "7")
    monkeypatch.setenv("TELEGRAM_SEND_REJECTED_ALERTS", "true")

    settings = type(
        "S",
        (),
        {
            "get": lambda self, key, default=None: {
                "monitoring.telegram.enabled": False,
                "monitoring.telegram.timeout_seconds": 10,
                "monitoring.send_rejected_alerts": False,
                "monitoring.send_summary_alerts": False,
                "monitoring.telegram": {"bot_token": "", "chat_id": ""},
            }.get(key, default)
        },
    )()
    notifier = TelegramNotifier.from_settings(settings)

    assert notifier.config.enabled is True
    assert notifier.config.bot_token == "env-token"
    assert notifier.config.chat_id == "env-chat"
    assert notifier.config.timeout_seconds == 7.0
    assert notifier.config.send_rejected_alerts is True
