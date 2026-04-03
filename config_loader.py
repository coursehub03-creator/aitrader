"""Configuration loading helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


@dataclass(slots=True)
class Settings:
    """Small helper for dot-path settings retrieval."""

    raw: dict[str, Any]

    def get(self, dotted_path: str, default: Any = None) -> Any:
        value: Any = self.raw
        for part in dotted_path.split("."):
            if not isinstance(value, dict) or part not in value:
                return default
            value = value[part]
        return value


def load_settings(path: str | Path = "config/settings.yaml") -> Settings:
    """Load YAML settings and .env values with actionable errors."""
    load_dotenv()
    settings_path = Path(path)

    if not settings_path.exists():
        raise FileNotFoundError(
            f"Settings file not found: {settings_path}. "
            "Create it or pass --settings with a valid YAML file path."
        )

    with settings_path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}

    if not isinstance(payload, dict):
        raise ValueError(
            f"Settings file {settings_path} must contain a YAML mapping at the root."
        )

    return Settings(raw=payload)