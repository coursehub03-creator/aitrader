"""Watchlist endpoints backed by local JSON storage."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from api.schemas import WatchlistEnvelope, WatchlistItem

router = APIRouter(prefix="/watchlist", tags=["watchlist"])
WATCHLIST_PATH = Path("state/watchlist.json")


def _load_watchlist() -> list[str]:
    if not WATCHLIST_PATH.exists():
        return ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"]
    data = json.loads(WATCHLIST_PATH.read_text(encoding="utf-8"))
    items = data.get("symbols", []) if isinstance(data, dict) else []
    return [str(item).upper() for item in items]


def _save_watchlist(symbols: list[str]) -> None:
    WATCHLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    WATCHLIST_PATH.write_text(json.dumps({"symbols": symbols}, indent=2), encoding="utf-8")


@router.get("", response_model=WatchlistEnvelope)
def list_watchlist() -> WatchlistEnvelope:
    return WatchlistEnvelope(symbols=_load_watchlist())


@router.post("", response_model=WatchlistEnvelope)
def add_symbol(payload: WatchlistItem) -> WatchlistEnvelope:
    symbols = _load_watchlist()
    symbol = payload.symbol.upper().strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="symbol cannot be empty")
    if symbol not in symbols:
        symbols.append(symbol)
        _save_watchlist(symbols)
    return WatchlistEnvelope(symbols=symbols)


@router.delete("/{symbol}", response_model=WatchlistEnvelope)
def remove_symbol(symbol: str) -> WatchlistEnvelope:
    symbols = [item for item in _load_watchlist() if item != symbol.upper()]
    _save_watchlist(symbols)
    return WatchlistEnvelope(symbols=symbols)
