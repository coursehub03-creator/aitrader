"use client";

import { useI18n } from "@/features/shared/i18n";

export function WatchlistPanel() {
  const { t } = useI18n();

  return (
    <>
      <h2>{t("watchlist.title")}</h2>
      <p>{t("watchlist.subtitle")}</p>
    </>
  );
}