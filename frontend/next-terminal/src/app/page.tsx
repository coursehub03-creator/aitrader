"use client";

import { AlertsHistoryPanel } from "@/features/alerts/components/alerts-history-panel";
import { LiveChartWorkspace } from "@/features/charts/components/live-chart-workspace";
import { LearningCenterPanel } from "@/features/learning/components/learning-center-panel";
import { RecommendationSidePanel } from "@/features/recommendations/components/recommendation-side-panel";
import { I18nProvider } from "@/features/shared/i18n";
import { WatchlistPanel } from "@/features/watchlist/components/watchlist-panel";

function TerminalPage() {
  return (
    <main className="terminal-grid">
      <section className="panel watchlist">
        <WatchlistPanel />
      </section>
      <section className="panel workspace">
        <LiveChartWorkspace />
      </section>
      <section className="panel recommendations">
        <RecommendationSidePanel />
      </section>
      <section className="bottom">
        <div className="panel">
          <AlertsHistoryPanel />
        </div>
        <div className="panel">
          <LearningCenterPanel />
        </div>
      </section>
    </main>
  );
}

export default function HomePage() {
  return (
    <I18nProvider>
      <TerminalPage />
    </I18nProvider>
  );
}
