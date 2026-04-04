"use client";

import { useI18n } from "@/features/shared/i18n";

export function LiveChartWorkspace() {
  const { t } = useI18n();
  return (
    <>
      <h2>{t("charts.title")}</h2>
      <p>{t("charts.subtitle")}</p>
    </>
  );
}
