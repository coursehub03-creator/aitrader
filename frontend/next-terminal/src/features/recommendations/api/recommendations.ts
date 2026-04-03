import { apiGet } from "@/lib/api-client";

export type RecommendationPayload = { recommendation: Record<string, unknown> };

export function fetchLatestRecommendation(symbol: string, timeframe: string) {
  return apiGet<RecommendationPayload>(`/recommendations/latest?symbol=${symbol}&timeframe=${timeframe}`);
}
