import { apiGet } from "@/features/shared/api-client";

export type WatchlistPayload = { symbols: string[] };

export function fetchWatchlist() {
  return apiGet<WatchlistPayload>("/watchlist");
}
