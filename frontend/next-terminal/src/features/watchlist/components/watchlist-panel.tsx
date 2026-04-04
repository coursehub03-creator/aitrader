"use client";

import { useI18n, type Language } from "@/features/shared/i18n";

export function WatchlistPanel() {
  const { t, language, setLanguage } = useI18n();

  return (
    <>
      <div className="sidebar-language-switcher" role="group" aria-label={t("lang.toggle")}>
        <span>{t("lang.toggle")}</span>
        {["en", "ar"].map((lang) => {
          const current = lang as Language;
          return (
            <button
              key={lang}
              type="button"
              className={language === current ? "active" : ""}
              onClick={() => setLanguage(current)}
            >
              {current === "en" ? t("lang.english") : t("lang.arabic")}
            </button>
          );
        })}
      </div>
      <h2>{t("watchlist.title")}</h2>
      <p>{t("watchlist.subtitle")}</p>
    </>
  );
}
