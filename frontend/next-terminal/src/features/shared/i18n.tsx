"use client";

import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type Language = "en" | "ar";

type TranslationValue = string;
type TranslationMap = Record<string, TranslationValue>;

const translations: Record<Language, TranslationMap> = {
  en: {
    "lang.english": "English",
    "lang.arabic": "العربية",
    "lang.toggle": "Language",

    "watchlist.title": "Watchlist",
    "watchlist.subtitle": "Symbols and quick switching UI scaffold.",

    "charts.title": "Live Chart Workspace",
    "charts.subtitle": "TradingView-like workspace placeholder. Integrate lightweight-charts now, TradingView widget later if licensed.",

    "recommendations.title": "Recommendation Panel",
    "recommendations.subtitle": "Action, confidence, strategy rationale, SL/TP context.",

    "alerts.title": "Alerts & History",
    "alerts.subtitle": "Live alert feed, suppression reasons, and terminal event history.",

    "learning.title": "Self-Learning Center",
    "learning.subtitle": "Historical MT5 data ingestion, validation, and learning diagnostics.",
  },
  ar: {
    "lang.english": "English",
    "lang.arabic": "العربية",
    "lang.toggle": "اللغة",

    "watchlist.title": "قائمة المراقبة",
    "watchlist.subtitle": "الرموز وواجهة التبديل السريع بين الأدوات.",

    "charts.title": "مساحة الرسم البياني المباشر",
    "charts.subtitle": "واجهة شبيهة بـ TradingView. يمكن دمج lightweight-charts الآن وودجت TradingView لاحقًا عند توفر الترخيص.",

    "recommendations.title": "لوحة التوصيات",
    "recommendations.subtitle": "الإجراء، مستوى الثقة، مبررات الاستراتيجية، وسياق وقف الخسارة/جني الربح.",

    "alerts.title": "التنبيهات والسجل",
    "alerts.subtitle": "خلاصة التنبيهات الحية، أسباب المنع، وسجل أحداث الطرفية.",

    "learning.title": "مركز التعلّم الذاتي",
    "learning.subtitle": "استيراد بيانات MT5 التاريخية، التحقق التاريخي، وتشخيصات التعلّم.",
  },
};

type I18nContextValue = {
  language: Language;
  setLanguage: (language: Language) => void;
  t: (key: string, fallback?: string) => string;
  dir: "ltr" | "rtl";
};

const I18nContext = createContext<I18nContextValue | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [language, setLanguage] = useState<Language>("en");

  useEffect(() => {
    document.documentElement.lang = language;
    document.documentElement.dir = language === "ar" ? "rtl" : "ltr";
  }, [language]);

  const value = useMemo<I18nContextValue>(
    () => ({
      language,
      setLanguage,
      dir: language === "ar" ? "rtl" : "ltr",
      t: (key: string, fallback?: string) => translations[language][key] ?? fallback ?? key,
    }),
    [language],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const ctx = useContext(I18nContext);
  if (!ctx) {
    throw new Error("useI18n must be used within I18nProvider");
  }
  return ctx;
}
