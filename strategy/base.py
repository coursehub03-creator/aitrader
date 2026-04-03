"""Strategy interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

from core.types import StrategySignal


class TradingStrategy(ABC):
    name: str

    @abstractmethod
    def generate_signal(self, df: pd.DataFrame, params: dict[str, Any]) -> StrategySignal | None:
        ...
