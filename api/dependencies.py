"""Dependency providers for API routes."""

from __future__ import annotations

from functools import lru_cache

from ui.dashboard_service import DashboardService


@lru_cache(maxsize=1)
def get_dashboard_service() -> DashboardService:
    """Return a cached dashboard service shared across API handlers."""
    return DashboardService()
