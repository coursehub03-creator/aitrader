"use client";

import { useI18n } from "@/features/shared/i18n";

export function RecommendationSidePanel() {
  const { t } = useI18n();
  return (
    <>
      <h2>{t("recommendations.title")}</h2>
      <p>{t("recommendations.subtitle")}</p>
    </>
  );
}
