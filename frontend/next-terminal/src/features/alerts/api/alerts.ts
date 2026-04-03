import { apiGet } from "@/lib/api-client";

export type AlertRowsPayload = { rows: Array<Record<string, unknown>> };

export function fetchAlerts(limit = 100) {
  return apiGet<AlertRowsPayload>(`/alerts/history?limit=${limit}`);
}
