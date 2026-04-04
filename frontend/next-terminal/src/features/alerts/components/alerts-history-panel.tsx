"use client";

import { useI18n } from "@/features/shared/i18n";

export function AlertsHistoryPanel() {
  const { t } = useI18n();
  return (
    <>
      <h2>{t("alerts.title")}</h2>
      <p>{t("alerts.subtitle")}</p>
    </>
  );
}
