import { apiGet } from "@/features/shared/api-client";

export type CandlePayload = {
  symbol: string;
  timeframe: string;
  bars: number;
  status_message: string;
  candles: Array<Record<string, unknown>>;
};

export function fetchCandles(symbol: string, timeframe: string, bars = 300) {
  return apiGet<CandlePayload>(`/market/candles?symbol=${symbol}&timeframe=${timeframe}&bars=${bars}`);
}
