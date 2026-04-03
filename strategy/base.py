"""Strategy interfaces and shared contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

from core.types import StrategySignal


class BaseStrategy(ABC):
    name: str

    @property
    @abstractmethod
    def parameter_schema(self) -> dict[str, dict[str, Any]]:
        """Optimization-ready parameter schema for strategy params."""

    @abstractmethod
    def generate_signal(self, df: pd.DataFrame, params: dict[str, Any]) -> StrategySignal:
        """Return normalized strategy signal object."""


# Backward compatibility alias
TradingStrategy = BaseStrategy
