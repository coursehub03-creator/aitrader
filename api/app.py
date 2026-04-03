"""FastAPI application factory for the AITrader migration layer."""

from __future__ import annotations

from fastapi import FastAPI

from api.routers import alerts, learning, market, paper_trades, recommendations, watchlist
from api.schemas import APIStatus


def create_app() -> FastAPI:
    """Build the FastAPI app with modular trading-terminal endpoints."""
    app = FastAPI(
        title="AITrader API",
        version="0.1.0",
        description="Incremental service layer powering migration from Streamlit to a modern web terminal.",
    )

    @app.get("/health", response_model=APIStatus, tags=["system"])
    def health() -> APIStatus:
        return APIStatus()

    app.include_router(recommendations.router)
    app.include_router(market.router)
    app.include_router(watchlist.router)
    app.include_router(paper_trades.router)
    app.include_router(learning.router)
    app.include_router(alerts.router)
    return app


app = create_app()
