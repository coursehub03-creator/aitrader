"""Telegram alert notifier."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests

from core.types import FinalRecommendation

LOGGER = logging.getLogger(__name__)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class TelegramConfig:
    enabled: bool = False
    bot_token: str = "8729539516:AAHbpZMCGekzDiGV_BvIVGj_VKxKgXikkeA"
    chat_id: str = "571073553"
    timeout_seconds: float = 10.0
    send_rejected_alerts: bool = False
    send_summary_alerts: bool = False


class TelegramNotifier:
    """Best-effort Telegram notifier for recommendation alerts."""

    def __init__(self, config: TelegramConfig) -> None:
        self.config = config

    @classmethod
    def from_settings(cls, settings: Any) -> "TelegramNotifier":
        telegram_root = settings.get("monitoring.telegram", {}) if hasattr(settings, "get") else {}
        enabled_setting = bool(settings.get("monitoring.telegram.enabled", False)) if hasattr(settings, "get") else False
        token = str(
            (telegram_root.get("bot_token") if isinstance(telegram_root, dict) else "")
            or os.getenv("TELEGRAM_BOT_TOKEN")
            or ""
        )
        chat_id = str(
            (telegram_root.get("chat_id") if isinstance(telegram_root, dict) else "")
            or os.getenv("TELEGRAM_CHAT_ID")
            or ""
        )
        return cls(
            TelegramConfig(
                enabled=_env_bool("TELEGRAM_ENABLED", enabled_setting),
                bot_token=token,
                chat_id=chat_id,
                timeout_seconds=float(os.getenv("TELEGRAM_TIMEOUT_SECONDS", str(settings.get("monitoring.telegram.timeout_seconds", 10)))),
                send_rejected_alerts=_env_bool(
                    "TELEGRAM_SEND_REJECTED_ALERTS",
                    bool(settings.get("monitoring.send_rejected_alerts", False)),
                ),
                send_summary_alerts=_env_bool(
                    "TELEGRAM_SEND_SUMMARY_ALERTS",
                    bool(settings.get("monitoring.send_summary_alerts", False)),
                ),
            )
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.config.enabled and self.config.bot_token and self.config.chat_id)

    def build_message(self, recommendation: FinalRecommendation, alert_type: str = "strong_trade_alert") -> str:
        action = recommendation.action.value if hasattr(recommendation.action, "value") else recommendation.action
        ts = recommendation.timestamp.replace(tzinfo=timezone.utc).isoformat(timespec="seconds")
        reasons = "\n".join(f"- {reason}" for reason in recommendation.reasons) if recommendation.reasons else "- n/a"
        headline = {
            "strong_trade_alert": "📌 *Trading Recommendation Alert*",
            "trade_blocked_by_news": "📌 *Trade Blocked: News Risk*",
            "trade_blocked_by_market_closed": "📌 *Trade Blocked: Market Closed*",
            "trade_blocked_by_filters": "📌 *Trade Blocked: Quality Filters*",
            "rejected_signal_alert": "📌 *Rejected Setup Notice*",
        }.get(alert_type, "📌 *Monitoring Alert*")
        return (
            f"{headline}\n\n"
            "*Instrument*\n"
            f"- Symbol: `{recommendation.symbol}`\n"
            f"- Timeframe: `{recommendation.timeframe}`\n"
            f"- Action: *{action}*\n\n"
            "*Signal Quality*\n"
            f"- Signal Strength: `{recommendation.signal_strength}`\n"
            f"- Confidence: `{recommendation.confidence:.2%}`\n"
            f"- Risk/Reward: `{recommendation.risk_reward:.2f}`\n"
            f"- Selected Strategy: `{recommendation.selected_strategy}`\n\n"
            "*Price Levels*\n"
            f"- Entry: `{recommendation.entry:.5f}`\n"
            f"- Stop Loss: `{recommendation.stop_loss:.5f}`\n"
            f"- Take Profit: `{recommendation.take_profit:.5f}`\n\n"
            "*Execution Context*\n"
            f"- Market Status: `{recommendation.market_status}`\n"
            f"- News Status: `{recommendation.news_status}`\n"
            f"- Spread State: `{recommendation.spread_state}`\n"
            f"- Session State: `{recommendation.session_state}`\n"
            f"- Timestamp (UTC): `{ts}`\n\n"
            "*Reasons*\n"
            f"{reasons}"
        )

    def build_summary_message(self, summary: dict[str, Any]) -> str:
        ts = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
        return (
            "📌 *Monitoring Summary*\n\n"
            f"- Period: `{summary.get('period', 'daily')}`\n"
            f"- Strong signals: `{summary.get('strong_signals', 0)}`\n"
            f"- Rejected signals: `{summary.get('rejected_signals', 0)}`\n"
            f"- Best symbols: `{summary.get('best_symbols', 'n/a')}`\n"
            f"- Paper trading: `{summary.get('paper_trading_summary', 'n/a')}`\n"
            f"- Generated (UTC): `{ts}`"
        )

    def _send_raw(self, text: str) -> tuple[bool, str]:
        if not self.config.enabled:
            return False, "telegram_disabled"
        if not self.is_configured:
            LOGGER.info("Telegram is enabled but bot token/chat id are missing.")
            return False, "telegram_not_configured"

        url = f"https://api.telegram.org/bot{self.config.bot_token}/sendMessage"
        payload: dict[str, Any] = {
            "chat_id": self.config.chat_id,
            "text": text,
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

    def send_recommendation_alert(
        self,
        recommendation: FinalRecommendation,
        alert_type: str = "strong_trade_alert",
    ) -> tuple[bool, str]:
        return self._send_raw(self.build_message(recommendation, alert_type=alert_type))

    def send_summary_alert(self, summary: dict[str, Any]) -> tuple[bool, str]:
        if not self.config.send_summary_alerts:
            return False, "summary_alerts_disabled"
        return self._send_raw(self.build_summary_message(summary))
