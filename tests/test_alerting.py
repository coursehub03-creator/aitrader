from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.types import FinalRecommendation, SignalAction
from monitoring.alerts import AlertCooldownStore, AlertPolicy
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
