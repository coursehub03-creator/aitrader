import { AlertsHistoryPanel } from "@/features/alerts/components/alerts-history-panel";
import { LiveChartWorkspace } from "@/features/charts/components/live-chart-workspace";
import { LearningCenterPanel } from "@/features/learning/components/learning-center-panel";
import { RecommendationSidePanel } from "@/features/recommendations/components/recommendation-side-panel";
import { WatchlistPanel } from "@/features/watchlist/components/watchlist-panel";

export default function HomePage() {
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
