"""Telegram alert notifier."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timezone
from typing import Any

import requests

from core.types import FinalRecommendation

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class TelegramConfig:
    enabled: bool = False
    bot_token: str = ""
    chat_id: str = ""
    timeout_seconds: float = 10.0


class TelegramNotifier:
    """Best-effort Telegram notifier for recommendation alerts."""

    def __init__(self, config: TelegramConfig) -> None:
        self.config = config

    @property
    def is_configured(self) -> bool:
        return bool(self.config.enabled and self.config.bot_token and self.config.chat_id)

    def build_message(self, recommendation: FinalRecommendation) -> str:
        action = recommendation.action.value if hasattr(recommendation.action, "value") else recommendation.action
        ts = recommendation.timestamp.replace(tzinfo=timezone.utc).isoformat(timespec="seconds")
        reasons = "\n".join(f"- {reason}" for reason in recommendation.reasons) if recommendation.reasons else "- n/a"
        return (
            "🚨 *Strong Trading Opportunity*\n"
            f"*Symbol:* `{recommendation.symbol}`\n"
            f"*Timeframe:* `{recommendation.timeframe}`\n"
            f"*Action:* *{action}*\n"
            f"*Entry:* `{recommendation.entry:.5f}`\n"
            f"*Stop Loss:* `{recommendation.stop_loss:.5f}`\n"
            f"*Take Profit:* `{recommendation.take_profit:.5f}`\n"
            f"*Confidence:* `{recommendation.confidence:.2%}`\n"
            f"*Signal Strength:* `{recommendation.signal_strength}`\n"
            f"*Selected Strategy:* `{recommendation.selected_strategy}`\n"
            f"*Market Status:* `{recommendation.market_status}`\n"
            f"*News Status:* `{recommendation.news_status}`\n"
            f"*Timestamp (UTC):* `{ts}`\n"
            "*Reasons:*\n"
            f"{reasons}"
        )

    def send_recommendation_alert(self, recommendation: FinalRecommendation) -> tuple[bool, str]:
        if not self.config.enabled:
            return False, "telegram_disabled"
        if not self.is_configured:
            return False, "telegram_not_configured"

        url = f"https://api.telegram.org/bot{self.config.bot_token}/sendMessage"
        payload: dict[str, Any] = {
            "chat_id": self.config.chat_id,
            "text": self.build_message(recommendation),
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }

        try:
            response = requests.post(url, json=payload, timeout=self.config.timeout_seconds)
            if response.status_code >= 400:
                LOGGER.warning("Telegram alert rejected: status=%s body=%s", response.status_code, response.text)
                return False, f"telegram_http_{response.status_code}"
        except Exception as exc:  # noqa: BLE001 - defensive network isolation
            LOGGER.warning("Telegram alert failed safely: %s", exc)
            return False, "telegram_unavailable"

        return True, "sent"
