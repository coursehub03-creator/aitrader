# Next Terminal Frontend Scaffold

This folder contains the incremental **Next.js terminal UI scaffold** for replacing Streamlit over time.

## Planned feature slices

- `features/charts`: TradingView-like workspace integration shell
- `features/watchlist`: symbol list + selection state
- `features/recommendations`: recommendation side panel
- `features/alerts`: alert history + active alert rail
- `features/learning`: self-learning center dashboards

## API integration

All data access should go through typed client modules in `features/*/api`, targeting the FastAPI service layer (`/api/...` routes in this repository's Python backend).

## Start locally (once dependencies are installed)

```bash
cd frontend/next-terminal
npm install
npm run dev
```
