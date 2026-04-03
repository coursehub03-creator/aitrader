# Project guidance

## Goals
- Build a Python trading recommendation system for MetaTrader 5
- Recommendations only, no live execution
- Multi-symbol support
- News-first filtering
- Paper trading and self-optimization

## Constraints
- Do not use screen reading, OCR, or browser scraping that is brittle unless wrapped behind a provider abstraction
- Use MT5 as the market data source
- Design the news layer so providers can be swapped later
- Prefer clean, modular architecture
- Add logging, tests, and clear README instructions

## Validation
- Run tests after changes when possible
- Keep imports valid
- Keep CLI runnable
