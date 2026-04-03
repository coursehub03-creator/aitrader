"""Tests for FastAPI migration scaffold."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from api.app import create_app
from api.dependencies import get_dashboard_service
from api.routers import watchlist as watchlist_router


class FakeService:
    def generate_recommendation(self, symbol: str, timeframe: str):
        return type("Rec", (), {"symbol": symbol, "timeframe": timeframe})()

    def recommendation_to_record(self, recommendation):
        return {
            "symbol": recommendation.symbol,
            "timeframe": recommendation.timeframe,
            "action": "NO_TRADE",
            "timestamp": datetime.utcnow().isoformat(),
        }

    def refresh_market_data(self, symbol: str, timeframe: str, bars: int = 300):
        return pd.DataFrame([{"time": "2026-01-01T00:00:00Z", "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05}]), "ok"

    def load_paper_trades(self, limit: int = 100):
        return pd.DataFrame([{"symbol": "EURUSD", "pnl": 12.5}])

    def recent_alert_events(self, limit: int = 100):
        return pd.DataFrame([{"symbol": "EURUSD", "status": "sent"}])

    def learning_center_payload(self):
        return {"health": {"status": "good"}, "events": pd.DataFrame([{"event": "optimizer_run"}])}

    def fetch_historical_data(self, symbol: str, timeframe: str, lookback_days: int):
        return {
            "success": True,
            "symbol": symbol.upper(),
            "timeframe": timeframe.upper(),
            "lookback_days": lookback_days,
            "candles_fetched": 42,
            "date_start": "2026-01-01T00:00:00+00:00",
            "date_end": "2026-01-02T00:00:00+00:00",
            "storage_path": "data/market_history/EURUSD_M5.csv",
            "status_message": "Fetched 42 candles successfully.",
        }


    def run_historical_validation(self):
        return pd.DataFrame(
            [
                {
                    "symbol": "EURUSD",
                    "timeframe": "M5",
                    "strategy": "trend_rsi",
                    "rank": 1,
                    "total_trades": 25,
                    "win_rate": 0.56,
                    "loss_rate": 0.44,
                    "net_pnl": 18.2,
                    "max_drawdown": 2.3,
                    "profit_factor": 1.42,
                    "expectancy": 0.73,
                    "score": 61.5,
                }
            ]
        )

    def historical_data_summary(self):
        return pd.DataFrame(
            [
                {
                    "symbol": "EURUSD",
                    "timeframe": "M5",
                    "candles": 42,
                    "data_start": "2026-01-01T00:00:00+00:00",
                    "data_end": "2026-01-02T00:00:00+00:00",
                }
            ]
        )


def _client(tmp_path) -> TestClient:
    watchlist_router.WATCHLIST_PATH = tmp_path / "watchlist.json"
    app = create_app()
    app.dependency_overrides[get_dashboard_service] = lambda: FakeService()
    return TestClient(app)


def test_health_endpoint(tmp_path) -> None:
    client = _client(tmp_path)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_recommendation_endpoint(tmp_path) -> None:
    client = _client(tmp_path)
    response = client.get("/recommendations/latest?symbol=EURUSD&timeframe=M5")
    assert response.status_code == 200
    payload = response.json()["recommendation"]
    assert payload["symbol"] == "EURUSD"
    assert payload["timeframe"] == "M5"


def test_market_endpoint(tmp_path) -> None:
    client = _client(tmp_path)
    response = client.get("/market/candles?symbol=EURUSD&timeframe=M5&bars=10")
    assert response.status_code == 200
    payload = response.json()
    assert payload["bars"] == 10
    assert len(payload["candles"]) == 1


def test_watchlist_crud_endpoints(tmp_path) -> None:
    client = _client(tmp_path)
    response = client.get("/watchlist")
    assert response.status_code == 200
    assert "symbols" in response.json()

    add_response = client.post("/watchlist", json={"symbol": "nzdusd"})
    assert add_response.status_code == 200
    assert "NZDUSD" in add_response.json()["symbols"]

    remove_response = client.delete("/watchlist/NZDUSD")
    assert remove_response.status_code == 200
    assert "NZDUSD" not in remove_response.json()["symbols"]


def test_watchlist_endpoint_handles_malformed_json(tmp_path) -> None:
    watchlist_path = tmp_path / "watchlist.json"
    watchlist_path.write_text("{ broken", encoding="utf-8")
    client = _client(tmp_path)
    response = client.get("/watchlist")
    assert response.status_code == 200
    assert response.json()["symbols"] == ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"]


def test_learning_historical_fetch_endpoint(tmp_path) -> None:
    client = _client(tmp_path)
    response = client.post(
        "/learning/history/fetch",
        json={"symbol": "EURUSD", "timeframe": "M5", "lookback_days": 90},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["candles_fetched"] == 42


def test_learning_historical_inventory_endpoint(tmp_path) -> None:
    client = _client(tmp_path)
    response = client.get("/learning/history/inventory")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["rows"]) == 1
    assert payload["rows"][0]["symbol"] == "EURUSD"


def test_learning_validation_run_endpoint(tmp_path) -> None:
    client = _client(tmp_path)
    response = client.post('/learning/validation/run', json={'run': True})
    assert response.status_code == 200
    payload = response.json()
    assert len(payload['rows']) == 1
    assert payload['rows'][0]['strategy'] == 'trend_rsi'


def test_learning_validation_results_endpoint(tmp_path) -> None:
    client = _client(tmp_path)
    response = client.get('/learning/validation/results')
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload['rows'], list)
