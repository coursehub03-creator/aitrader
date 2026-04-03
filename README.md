# AITrader (MT5 Recommendation-Only System)

Production-ready Python project for **AI-assisted trading recommendations** using **MetaTrader 5** data.

## Safety Scope

- ✅ Recommendations only (`Buy` / `Sell` / `No Trade`)
- ✅ Paper-trading simulation only
- ❌ No live order execution

## Architecture

```text
app/                # CLI entrypoint
core/               # MT5 client, indicators, paper trading, shared types
news/               # News provider abstraction + ForexFactory provider + filter
strategy/           # Strategy interface + TrendRSI + BreakoutATR
learning/           # Evaluator + parameter grid search optimizer
recommendation/     # Recommendation orchestration engine
config/             # settings.yaml
logs/               # Runtime artifacts (e.g. paper_trade_results.jsonl)
tests/              # Unit tests
```

## Installation

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

## Configuration

Edit `config/settings.yaml`:

- `app.log_level`: logging level
- `app.data_bars`: number of candles to fetch
- `news.endpoint`: ForexFactory-compatible JSON endpoint
- `news.high_impact_cooldown_before_min` / `after_min`: news blocking window
- `strategy.*`: default strategy parameters
- `learning.parameter_grid`: optimization search space

Optional environment variables in `.env`:

- `MT5_PATH`
- `MT5_LOGIN`
- `MT5_PASSWORD`
- `MT5_SERVER`

## Usage

Run from repository root:

```bash
python -m app.main --symbol EURUSD --timeframe M5
```

Example output:

```json
{
  "symbol": "EURUSD",
  "timeframe": "M5",
  "action": "No Trade",
  "entry": 0.0,
  "stop_loss": 0.0,
  "take_profit": 0.0,
  "confidence": 0.0,
  "reason": "MetaTrader5 Python package is not installed. Install dependencies and ensure MT5 terminal is available.",
  "contributing_strategies": []
}
```

## Error Handling Notes

- If `MetaTrader5` package is missing or MT5 terminal initialization fails, the app returns `No Trade` with a clear reason.
- If the news endpoint is missing, unreachable, or returns invalid payload, the app logs a warning and continues safely with no events.
- If `config/settings.yaml` is missing or malformed, CLI prints a clear actionable error.

## Testing

```bash
pytest -q
```

## Logging

Structured log format is enabled globally:

```text
2026-04-03T12:00:00Z level=INFO logger=recommendation.engine message=...
```

Paper-trade signals are appended to:

- `logs/paper_trade_results.jsonl`
