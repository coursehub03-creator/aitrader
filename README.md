# AITrader - MT5 Trading Recommendation System

A production-style Python project for **AI-assisted trading recommendations** using **MetaTrader 5** market data.

## Important Safety Scope

- ✅ Recommendations only (`Buy` / `Sell` / `No Trade`)
- ✅ Paper-trading simulation only
- ❌ No live order execution

## Features

- MT5 connector with safe import handling (app does not crash when MT5 package is unavailable)
- Multi-symbol recommendation flow (`--symbol`)
- News provider abstraction (swappable providers)
- ForexFactory-compatible provider implementation
- High-impact news cooldown filter (blocks recommendations around key events)
- Two starter strategies:
  - Trend + RSI
  - Breakout + ATR
- Paper trade simulator
- Strategy evaluator and score ranking
- Grid-search parameter optimizer
- Modular architecture for long-term development

## Project Structure

```text
app/
core/
news/
strategy/
learning/
recommendation/
config/
logs/
tests/
```

## Setup

### Windows (PowerShell)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

### macOS/Linux

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Configure

Edit `config/settings.yaml` for:
- symbols-to-currency mapping for news filtering
- strategy default parameters
- optimizer parameter grids

## Run

```bash
python -m app.main --symbol EURUSD --timeframe M5
```

### Example Command (as requested)

```bash
python -m app.main --symbol EURUSD --timeframe M5
```

## Testing

```bash
pytest -q
```

## Notes About MT5 Availability

If MetaTrader5 is not installed or cannot initialize:
- the app logs a warning,
- returns a safe `No Trade` recommendation,
- and continues without crashing.
