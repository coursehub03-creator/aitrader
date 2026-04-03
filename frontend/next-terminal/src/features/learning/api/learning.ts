import { apiGet, apiPost } from "@/features/shared/api-client";

export function fetchLearningCenter() {
  return apiGet<Record<string, unknown>>("/learning/center");
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
