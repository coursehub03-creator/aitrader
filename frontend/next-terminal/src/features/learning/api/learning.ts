import { apiGet } from "@/lib/api-client";

export function fetchLearningCenter() {
  return apiGet<Record<string, unknown>>("/learning/center");
}
