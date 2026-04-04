import { apiGet, apiPost } from "@/features/shared/api-client";

export type LearningCenterPayload = {
  active: Array<Record<string, unknown>>;
  candidates: Array<Record<string, unknown>>;
  state_changes: Array<Record<string, unknown>>;
  historical_validation: Array<Record<string, unknown>>;
  paper_trades: Array<Record<string, unknown>>;
  events: Array<Record<string, unknown>>;
  best_config: Array<Record<string, unknown>>;
  state_changes_prepared: Array<Record<string, unknown>>;
  metadata: Record<string, unknown>;
  health: Record<string, unknown>;
};

export function fetchLearningCenter() {
  return apiGet<LearningCenterPayload>("/learning/center");
}

export type HistoricalFetchPayload = {
  success: boolean;
  symbol: string;
  timeframe: string;
  lookback_days: number;
  candles_fetched: number;
  date_start: string;
  date_end: string;
  storage_path: string;
  status_message: string;
};

export type HistoryInventoryPayload = {
  rows: Array<{
    symbol: string;
    timeframe: string;
    candles: number;
    data_start: string;
    data_end: string;
  }>;
};

export function fetchHistoricalData(symbol: string, timeframe: string, lookbackDays: number) {
  return apiPost<HistoricalFetchPayload, { symbol: string; timeframe: string; lookback_days: number }>(
    "/learning/history/fetch",
    { symbol, timeframe, lookback_days: lookbackDays },
  );
}

export function fetchHistoryInventory() {
  return apiGet<HistoryInventoryPayload>("/learning/history/inventory");
}

export type HistoricalValidationPayload = {
  rows: Array<Record<string, unknown>>;
};

export function runHistoricalValidation() {
  return apiPost<HistoricalValidationPayload, { run: boolean }>("/learning/validation/run", { run: true });
}

export function fetchHistoricalValidationResults() {
  return apiGet<HistoricalValidationPayload>("/learning/validation/results");
}
