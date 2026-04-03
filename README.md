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
- Strategy layer with a base strategy contract (`BaseStrategy`)
- Strategy registry/factory for pluggable strategy loading
- Two starter strategies:
  - Trend + RSI
  - Breakout + ATR
- Normalized strategy signals (`BUY` / `SELL` / `NO_TRADE`) with entry/SL/TP/confidence/reasons
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
```

## News Layer

- `core.types.NewsEvent` is the normalized event model with:
  `event_id`, `title`, `currency`, `impact`, `event_time`, `actual`,
  `forecast`, `previous`, and `source`.
- `news.base.NewsProvider` defines the provider contract.
- `news.providers.build_news_provider(...)` resolves providers from settings
  (`forexfactory`, `none`), making the data source replaceable.
- `news.filter.NewsFilter` produces one of:
  - `block trading`
  - `reduce confidence`
  - `allow trading`
- `news.symbols.currencies_for_symbol(...)` maps symbol relevance by config
  (`news.symbols_map`) with a fallback split (e.g. `EURUSD -> EUR, USD`).
- If a provider is unavailable, the engine logs warnings and continues safely
  with no news events instead of crashing.
