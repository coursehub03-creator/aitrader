"""Watchlist endpoints backed by local JSON storage."""

from __future__ import annotations

import json
from pathlib import Path
import logging

from fastapi import APIRouter, HTTPException

from api.schemas import WatchlistEnvelope, WatchlistItem

router = APIRouter(prefix="/watchlist", tags=["watchlist"])
WATCHLIST_PATH = Path("state/watchlist.json")
LOGGER = logging.getLogger(__name__)
DEFAULT_SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"]


def _load_watchlist() -> list[str]:
    if not WATCHLIST_PATH.exists():
        return list(DEFAULT_SYMBOLS)
    try:
        raw = WATCHLIST_PATH.read_text(encoding="utf-8").strip()
        if not raw:
            LOGGER.warning("Watchlist file is empty at %s. Falling back to defaults.", WATCHLIST_PATH)
            return list(DEFAULT_SYMBOLS)
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        LOGGER.warning("Watchlist file is malformed at %s: %s. Falling back to defaults.", WATCHLIST_PATH, exc)
        return list(DEFAULT_SYMBOLS)
    except Exception as exc:
        LOGGER.warning("Watchlist file could not be read at %s: %s. Falling back to defaults.", WATCHLIST_PATH, exc)
        return list(DEFAULT_SYMBOLS)

    items = data.get("symbols", []) if isinstance(data, dict) else []
    cleaned: list[str] = []
    for item in items:
        symbol = str(item).upper().strip()
        if symbol and symbol not in cleaned:
            cleaned.append(symbol)
    return cleaned or list(DEFAULT_SYMBOLS)


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
