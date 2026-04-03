# AITrader Beta (MT5 Recommendation Assistant)

AITrader is a **local-first, operator-facing beta** for foreign-exchange and metals market analysis using **MetaTrader 5** candles.

It is intentionally scoped to:
- ✅ recommendation-only signals (`BUY`, `SELL`, `NO_TRADE`)
- ✅ paper-trading simulation
- ✅ human-in-the-loop operation
- ❌ no live order execution

---

## 1) Safety and Beta Scope

This repository is prepared as a near-final **beta release** for operator testing.

Core guardrails:
- Recommendations are advisory and can be blocked by market/news/risk filters.
- No broker execution path is implemented.
- Paper-trade and learning loops are local persistence workflows.
- MT5 is the market data source for both CLI and UI.

---

## 2) Architecture Overview

```text
app/                  CLI entrypoint and monitor/watch mode
api/                  FastAPI scaffold for service migration
core/                 MT5 client, indicators, shared types, paper trading
news/                 provider abstraction + filtering
strategy/             strategy contracts and concrete strategies
recommendation/       orchestration engine
learning/             validation, optimizer, persistence, unified scoring
monitoring/           monitor runtime state + alert policy/cooldown
notification/         Telegram notifier
ui/                   Streamlit terminal-style operator dashboard
config/               YAML configuration
db/                   SQLite learning and runtime storage
state/                active strategy and runtime state JSON files
data/                 historical/paper/optimizer artifacts
logs/                 cycle, alert, and learning logs
tests/                test suite
frontend/next-terminal/  future Next.js terminal scaffold
```

---

## 3) Setup

### Prerequisites
- Python 3.10+
- MetaTrader 5 terminal installed and logged in
- OS-level access to MT5 terminal process (typically Windows for live MT5 package)

### Install

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
```

### Configure
1. Copy or edit `config/settings.yaml`.
2. Fill MT5 terminal and account values.
3. Optionally configure Telegram values for alert delivery.

---

## 4) Running the System

## CLI (single recommendation)

```bash
python -m app --symbol EURUSD --timeframe M5
```

Alternative explicit module path:

```bash
python -m app.main --symbol EURUSD --timeframe M5
```

## Monitor mode (continuous loop)

```bash
python -m app --monitor --symbols EURUSD,GBPUSD,XAUUSD --timeframe M5 --interval 60
```

Notes:
- `--monitor` is an alias for `--watch`.
- `--cooldown` overrides alert cooldown seconds.
- Monitor cycles are persisted to `logs/monitor_cycles.jsonl`.

## Streamlit UI

```bash
streamlit run ui/app.py
```

The dashboard is local and reuses the same backend engine/persistence stack.

---

## 5) UI Overview (Operator Guide)

Primary UI capabilities:
- Symbol watchlist and quick switching
- Recommendation panel (action, confidence, RR, strategy, reasons)
- Market/news/session status strip
- Interactive market charting (candles + overlays)
- Paper-trade history and diagnostics
- Alert history and suppression visibility
- Learning center for validation/optimizer/promotions

The UI can run in monitor/watch style with periodic cycles while preserving operator state in session and local files.

---

## 6) Watch Mode and Alerting

Watch/monitor mode evaluates symbols at fixed intervals and applies:
1. recommendation eligibility policy
2. cooldown suppression
3. duplicate alert suppression
4. optional Telegram dispatch

Key files:
- `logs/monitor_cycles.jsonl`
- `logs/alert_history.jsonl`
- `logs/alert_state.json`
- `logs/alert_sent_history.jsonl`

UI-specific monitor traces are written to `logs/ui_monitor_cycles.jsonl` and `logs/ui_alert_history.csv`.

---

## 7) Historical Learning and Validation

Learning is split into transparent local workflows:
- historical data ingestion from MT5 candles
- historical validation reports
- optimizer runs (grid/randomized search)
- unified scorer combining historical and forward-paper performance
- candidate promotion/demotion lifecycle tracking

These pipelines are for **strategy ranking and recommendation quality** only.

---

## 8) Self-Learning Loop

The self-learning loop in this beta is **bounded and operator-driven**:
- update data
- run validation/optimizer
- score candidates
- promote/demote with explicit metrics and state history

No source code rewriting is used for learning state; state is persisted in structured local storage.

---

## 9) Telegram Alerts

Telegram integration is optional and used for operator notifications.

Typical setup (via `settings.yaml`):
- `telegram.enabled`
- `telegram.bot_token`
- `telegram.chat_id`
- alert behavior flags (including rejected-signal notifications)

If Telegram is disabled/misconfigured, recommendation generation still works locally.

---

## 10) Storage Layout

Persistent data locations:
- `data/market_history/` – market candle datasets
- `data/paper_trades/` – paper-trade exports
- `data/learning/` – learning and validation artifacts
- `data/optimizer/` – optimizer result snapshots
- `data/snapshots/` – optional checkpoints
- `state/` – active runtime and strategy state JSON
- `db/` – SQLite database (`learning.sqlite3`)
- `logs/` – monitor cycles, alerts, and diagnostics

---

## 11) Tests

Run all tests:

```bash
pytest -q
```

If your environment lacks optional test dependencies, install from `requirements.txt` and retry.

---

## 12) Known Limitations (Beta)

- MT5 package/runtime availability is environment dependent.
- Strategy set is intentionally conservative and starter-grade.
- Streamlit rerun model can be less smooth than dedicated JS terminals under very short refresh intervals.
- API layer is scaffolded but not yet the primary runtime path.
- No live trading execution by design.

---

## 13) Roadmap

### A) FastAPI service layer hardening
- complete endpoint parity with Streamlit panels
- formal response schemas and versioning
- background task scheduling and health endpoints

### B) React/Next.js frontend
- migrate operator panels to the Next.js terminal scaffold
- add richer chart interactions and panel docking
- consume FastAPI payloads with auth/session boundaries

### C) Trading-terminal migration
- run Streamlit and web terminal in parallel during parity phase
- promote web terminal after runbook and operational sign-off
- keep Streamlit as fallback console during transition

---

## 14) Release Readiness Checklist

- [x] Local-first architecture
- [x] Recommendation-only scope
- [x] Paper-trading-only execution model
- [x] CLI + monitor + Streamlit entrypoints documented
- [x] Tests runnable in a fully provisioned Python environment
- [x] Storage/logging paths defined for operations
