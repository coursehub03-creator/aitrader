# AITrader - MT5 Trading Recommendation System

A production-ready Python project for **AI-assisted trading recommendations** using **MetaTrader 5** market data.

## Important Safety Scope

- ✅ Recommendations only (`Buy` / `Sell` / `No Trade`)
- ✅ Paper-trading simulation only
- ❌ No live order execution

## Features

- MT5 connector with safe import handling (app does not crash when the MetaTrader5 package is unavailable)
- Market-open awareness (`market_status`: `open`, `closed`, `unavailable`, `mt5_unavailable`) before strategy aggregation
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
- Structured paper-trade persistence (CSV/SQLite)
- Strategy evaluator and leaderboard with risk filters
- Self-optimization layer with grid/randomized search, train/validation/forward scoring, and anti-overfit ranking
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
ui/                 # Streamlit operator dashboard
```

## Streamlit Operator Dashboard (Local)

The project includes a premium local dashboard for manual decision support:

- Recommendation Summary with highlighted action (`BUY` / `SELL` / `NO_TRADE`)
- Market + news gating visibility (including blocked states)
- Strategy diagnostics and reasons
- Recent recommendation history (persisted locally)
- Paper-trade simulation panel and trade history
- Strategy leaderboard based on paper-trade outcomes
- Debug/log panel for operator troubleshooting
- Optional watch mode for auto-monitoring + alert status visibility

### Run locally

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Start the dashboard from the repository root:

```bash
streamlit run ui/app.py
```

> Keep MetaTrader 5 open to enable live MT5 market access. If MT5 is closed or unavailable, the dashboard will safely show `mt5_unavailable` and continue running without crashing.

### Watch mode in Streamlit

- Enable **Auto Refresh** to run recurring cycles.
- Enable **Watch Mode (Alerts)** to evaluate/send Telegram alerts for strong opportunities only.
- Configure refresh interval from the sidebar.
- Dashboard now shows:
  - current monitoring state (`running`/`idle`)
  - latest alert status (`sent`, `suppressed`, `failed`, `not_evaluated`)
  - latest alert reason and alert history table

### Status meanings in the dashboard

`market_status`:
- `open`: Symbol is tradable and has recent market activity.
- `closed`: Market/session appears closed; recommendation is forced to `NO_TRADE`.
- `unavailable`: Symbol is missing/not tradable in MT5.
- `mt5_unavailable`: MT5 package or terminal is not reachable.

`mt5_connection_status`:
- `connected`: MT5 initialize succeeded for the current cycle.
- `unavailable`: MT5 initialize failed for the current cycle.

The dashboard top cards and the recommendation output now use the same backend recommendation payload as the single source of truth (including `market_status` and `mt5_connection_status`).

`news_status`:
- `clear`: No blocking event in effect.
- `blocked`: High-impact event blocks trading; action is forced to `NO_TRADE`.
- `reduced_confidence`: News risk exists, recommendation remains but with lower confidence.
- `unknown`: News provider failed or returned uncertain state.

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
## Paper Trading + Evaluation

- `core.paper_trading.PaperTrader` simulates opening and closing paper trades using
  entry/SL/TP logic over lookahead candles.
- Trade records include:
  `entry`, `exit_price`, `stop_loss`, `take_profit`, `side`, `open_time`,
  `close_time`, `outcome`, and `pnl`.
- `core.paper_trading.TradeStore` saves structured paper trades to:
  - CSV (`save_csv`)
  - SQLite (`save_sqlite`)
- `learning.evaluator.PerformanceEvaluator` builds a strategy leaderboard with:
  - total trades
  - win rate
  - loss rate
  - net pnl
  - average pnl
  - max drawdown
  - profit factor
  - expectancy
- Leaderboard excludes strategies that have too few trades (`min_trades`) or too
  much drawdown (`max_drawdown_limit`).


## Self-Optimization Layer

- `learning.optimizer.ParameterOptimizer` supports `grid` and `randomized` parameter search.
- Each parameter set is evaluated using three stages:
  - training window
  - validation window
  - forward (paper-like) window
- Final ranking uses a robustness score weighted toward validation and forward performance, with an explicit overfitting penalty (`|train - validation|`).
- The optimizer stores top parameter candidates and writes JSON reports to `learning.optimization_report_dir` (default: `logs/optimization`).
- After each optimization cycle, only the best 2-3 strategies are activated (`learning.active_strategy_count`).
- Reports include the winning parameter sets and rationale for why they were selected.

## Market Status Behavior

- The recommendation engine checks market tradability *before* generating strategy output.
- Market status is attached to every final response via `market_status` with values:
  - `open` → normal strategy/news flow continues.
  - `closed` → engine returns `NO_TRADE` and neutralized entry/SL/TP/confidence values.
  - `unavailable` → symbol is missing or not tradable in MT5, returns `NO_TRADE`.
  - `mt5_unavailable` → MT5 package/terminal is unavailable, returns `NO_TRADE`.
- Terminal output now prints **Market Status** near the top so the operator sees session availability before reviewing strategy details.
- MT5 initialization includes safe retry behavior (up to 3 attempts with short delay by default).
- MT5 terminal path and login options can be configured in `config/settings.yaml` under `mt5.*` (`terminal_path`, `login`, `password`, `server`, retry settings).

## Monitor Mode + Telegram Alerts

### Configuration (`config/settings.yaml`)

```yaml
monitoring:
  interval_seconds: 300
  alert_cooldown_seconds: 900
  symbols: [EURUSD, GBPUSD, USDJPY]
  telegram:
    enabled: false
    bot_token: ""
    chat_id: ""
    timeout_seconds: 10
```

### Enable Telegram alerts

You can configure credentials in YAML or via environment variables:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Alerts are **best-effort**: failures are logged and never crash monitoring cycles.

### Run monitor mode from CLI

Single symbol:

```bash
python -m app.main --symbol EURUSD --monitor --interval 300
```

Multi-symbol:

```bash
python -m app.main --symbols EURUSD,GBPUSD,USDJPY --monitor --interval 300
```

Optional override cooldown:

```bash
python -m app.main --symbols EURUSD,GBPUSD --monitor --cooldown 1200
```

### Alert qualification policy (strong opportunities only)

Alerts are sent only when all conditions pass:
- market is open
- news is not blocked
- action is `BUY` or `SELL`
- signal strength is `strong`
- confidence >= configured minimum
- risk/reward >= configured minimum

Duplicate alerts are suppressed with per-symbol+direction cooldown.

### Monitoring persistence

Monitoring writes local logs to:
- `logs/monitor_cycles.jsonl` (cycle + recommendation + suppression reason)
- `logs/alert_history.jsonl` (alert outcomes)
- `logs/alert_state.json` (cooldown state)
