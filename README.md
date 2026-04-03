# AITrader - MT5 Trading Recommendation System

A production-ready Python project for **AI-assisted trading recommendations** using **MetaTrader 5** market data.

## Important Safety Scope

- ✅ Recommendations only (`Buy` / `Sell` / `No Trade`)
- ✅ Paper-trading simulation only
- ❌ No live order execution

## Features

- MT5 connector with safe import handling (app does not crash when the MetaTrader5 package is unavailable)
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