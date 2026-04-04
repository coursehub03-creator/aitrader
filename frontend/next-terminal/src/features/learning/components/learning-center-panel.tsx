"use client";

import { useEffect, useMemo, useState } from "react";

import {
  fetchHistoricalData,
  fetchHistoryInventory,
  fetchHistoricalValidationResults,
  fetchLearningCenter,
  runHistoricalValidation,
  type HistoricalFetchPayload,
  type HistoryInventoryPayload,
  type LearningCenterPayload,
} from "@/features/learning/api/learning";
import { useI18n } from "@/features/shared/i18n";

const SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"];
const TIMEFRAMES = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"];
const LOOKBACKS = [30, 90, 180, 365];

type ValidationRow = {
  symbol?: string;
  timeframe?: string;
  strategy?: string;
  rank?: number;
  total_trades?: number;
  win_rate?: number;
  loss_rate?: number;
  net_pnl?: number;
  max_drawdown?: number;
  profit_factor?: number;
  expectancy?: number;
  avg_reward_risk?: number;
  score?: number;
  final_validation_score?: number;
  params?: string;
  best_in_symbol_timeframe?: boolean;
};

type TradeRow = Record<string, unknown>;
type StrategySnapshot = Record<string, unknown>;

const LABELS = {
  en: {
    status: "Status",
    noFetch: "No historical fetch executed yet.",
    success: "Success",
    failure: "Failure",
    candles: "Candles fetched",
    dateRange: "Date range",
    symbol: "Symbol",
    timeframe: "Timeframe",
    lookback: "Lookback Range",
    days: "days",
    fetch: "Fetch Historical Data",
    fetching: "Fetching...",
    validate: "Run Historical Validation",
    validating: "Validating...",
    inventory: "History Inventory",
    noInventory: "No stored historical datasets yet.",
    coveredRange: "Covered Range",
    diagnostics: "Learning Diagnostics",
    strategyPerf: "Strategy Performance",
    learningProgression: "Learning Progression",
    strategyStates: "Strategy States",
    scoreMonitor: "Score Monitor",
    warnings: "Warnings",
    noWarnings: "No warnings. Learning loop looks stable.",
    totalTrades: "Total paper trades",
    winRate: "Win rate",
    lossRate: "Loss rate",
    netPnl: "Net PnL",
    maxDd: "Max drawdown",
    profitFactor: "Profit factor",
    expectancy: "Expectancy",
    perStrategy: "Per strategy stats",
    perSymbol: "Per symbol stats",
    bestPerSymbol: "Best strategy per symbol",
    last50: "Last 50 trades",
    last100: "Last 100 trades",
    trend: "Trend",
    improving: "Improving",
    stable: "Stable",
    degrading: "Degrading",
    active: "Active",
    candidate: "Candidate",
    probation: "Probation",
    disabled: "Disabled",
    historicalScore: "Historical score",
    recentScore: "Recent score",
    combinedScore: "Combined score",
    validation: "Historical Validation Results",
    ranked: "Ranked Strategies",
    topParams: "Top Parameter Sets",
    noValidation: "No validation results yet. Run historical validation.",
    noRanked: "No ranked strategies yet.",
    noParams: "No parameter sets yet.",
    strategy: "Strategy",
    rank: "Rank",
    trades: "Trades",
    params: "Params",
    state: "State",
    score: "Score",
  },
  ar: {
    status: "الحالة",
    noFetch: "لم يتم تنفيذ جلب البيانات التاريخية بعد.",
    success: "نجاح",
    failure: "فشل",
    candles: "الشموع التي تم جلبها",
    dateRange: "النطاق الزمني",
    symbol: "الرمز",
    timeframe: "الإطار الزمني",
    lookback: "فترة الرجوع",
    days: "يوم",
    fetch: "جلب البيانات التاريخية",
    fetching: "جارٍ الجلب...",
    validate: "تشغيل التحقق التاريخي",
    validating: "جارٍ التحقق...",
    inventory: "مخزون البيانات التاريخية",
    noInventory: "لا توجد مجموعات بيانات تاريخية محفوظة بعد.",
    coveredRange: "النطاق المغطى",
    diagnostics: "تشخيصات التعلّم",
    strategyPerf: "أداء الاستراتيجيات",
    learningProgression: "تطور التعلّم",
    strategyStates: "حالات الاستراتيجيات",
    scoreMonitor: "مراقبة الدرجات",
    warnings: "تحذيرات",
    noWarnings: "لا توجد تحذيرات. دورة التعلّم مستقرة.",
    totalTrades: "إجمالي صفقات التجربة",
    winRate: "نسبة الفوز",
    lossRate: "نسبة الخسارة",
    netPnl: "صافي الربح/الخسارة",
    maxDd: "أقصى تراجع",
    profitFactor: "معامل الربح",
    expectancy: "القيمة المتوقعة",
    perStrategy: "إحصائيات لكل استراتيجية",
    perSymbol: "إحصائيات لكل رمز",
    bestPerSymbol: "أفضل استراتيجية لكل رمز",
    last50: "آخر 50 صفقة",
    last100: "آخر 100 صفقة",
    trend: "الاتجاه",
    improving: "تحسّن",
    stable: "مستقر",
    degrading: "تراجع",
    active: "نشطة",
    candidate: "مرشحة",
    probation: "تحت المراقبة",
    disabled: "معطلة",
    historicalScore: "الدرجة التاريخية",
    recentScore: "الدرجة الحديثة",
    combinedScore: "الدرجة المجمعة",
    validation: "نتائج التحقق التاريخي",
    ranked: "تصنيف الاستراتيجيات",
    topParams: "أفضل مجموعات المعلمات",
    noValidation: "لا توجد نتائج تحقق بعد. شغّل التحقق التاريخي.",
    noRanked: "لا توجد استراتيجيات مصنفة بعد.",
    noParams: "لا توجد مجموعات معلمات بعد.",
    strategy: "الاستراتيجية",
    rank: "الترتيب",
    trades: "الصفقات",
    params: "المعلمات",
    state: "الحالة",
    score: "الدرجة",
  },
};

function num(value: unknown): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function pct(value: number) {
  return `${(value * 100).toFixed(1)}%`;
}

export function LearningCenterPanel() {
  const { language, t } = useI18n();
  const text = LABELS[language];
  const [symbol, setSymbol] = useState("EURUSD");
  const [timeframe, setTimeframe] = useState("M5");
  const [lookbackDays, setLookbackDays] = useState(90);
  const [status, setStatus] = useState<HistoricalFetchPayload | null>(null);
  const [inventory, setInventory] = useState<HistoryInventoryPayload["rows"]>([]);
  const [validationRows, setValidationRows] = useState<ValidationRow[]>([]);
  const [learningCenter, setLearningCenter] = useState<LearningCenterPayload | null>(null);
  const [busy, setBusy] = useState(false);
  const [validationBusy, setValidationBusy] = useState(false);

  const statusTone = useMemo(() => (!status ? "idle" : status.success ? "ok" : "error"), [status]);

  const rankedStrategies = useMemo(
    () =>
      [...validationRows].sort(
        (a, b) => Number(b.final_validation_score ?? b.score ?? 0) - Number(a.final_validation_score ?? a.score ?? 0),
      ),
    [validationRows],
  );

  const topParameterSets = useMemo(() => {
    const winners = validationRows.filter((row) => row.best_in_symbol_timeframe);
    return winners.length > 0 ? winners : rankedStrategies.slice(0, 10);
  }, [rankedStrategies, validationRows]);

  const diagnostics = useMemo(() => {
    const trades = (learningCenter?.paper_trades ?? []) as TradeRow[];
    const active = [...(learningCenter?.active ?? []), ...(learningCenter?.candidates ?? [])] as StrategySnapshot[];
    const total = trades.length;
    const wins = trades.filter((r) => String(r.outcome ?? r.result).toUpperCase().includes("WIN")).length;
    const losses = trades.filter((r) => String(r.outcome ?? r.result).toUpperCase().includes("LOSS")).length;
    const net = trades.reduce((acc, row) => acc + num(row.pnl), 0);
    const grossProfit = trades.reduce((acc, row) => acc + Math.max(num(row.pnl), 0), 0);
    const grossLoss = trades.reduce((acc, row) => acc + Math.min(num(row.pnl), 0), 0);
    const expectancy = total ? net / total : 0;

    let maxDrawdown = 0;
    let running = 0;
    let peak = 0;
    for (const row of [...trades].reverse()) {
      running += num(row.pnl);
      peak = Math.max(peak, running);
      maxDrawdown = Math.max(maxDrawdown, peak - running);
    }

    const byStrategy = Object.entries(
      trades.reduce<Record<string, { trades: number; wins: number; net: number }>>((acc, row) => {
        const key = String(row.strategy_name ?? row.strategy ?? "unknown");
        if (!acc[key]) acc[key] = { trades: 0, wins: 0, net: 0 };
        acc[key].trades += 1;
        acc[key].wins += String(row.outcome ?? row.result).toUpperCase().includes("WIN") ? 1 : 0;
        acc[key].net += num(row.pnl);
        return acc;
      }, {}),
    ).map(([strategy, item]) => ({ strategy, ...item, winRate: item.trades ? item.wins / item.trades : 0 }));

    const bySymbol = Object.entries(
      trades.reduce<Record<string, { trades: number; wins: number; net: number }>>((acc, row) => {
        const key = String(row.symbol ?? "unknown");
        if (!acc[key]) acc[key] = { trades: 0, wins: 0, net: 0 };
        acc[key].trades += 1;
        acc[key].wins += String(row.outcome ?? row.result).toUpperCase().includes("WIN") ? 1 : 0;
        acc[key].net += num(row.pnl);
        return acc;
      }, {}),
    ).map(([symbolName, item]) => ({ symbol: symbolName, ...item, winRate: item.trades ? item.wins / item.trades : 0 }));

    const bestBySymbol = Object.entries(
      active.reduce<Record<string, { strategy: string; score: number }>>((acc, row) => {
        const symbolName = String(row.symbol ?? "unknown");
        const strategy = String(row.strategy_name ?? "unknown");
        const score = num(row.combined_score);
        if (!acc[symbolName] || acc[symbolName].score < score) {
          acc[symbolName] = { strategy, score };
        }
        return acc;
      }, {}),
    ).map(([symbolName, item]) => ({ symbol: symbolName, strategy: item.strategy, score: item.score }));

    const recent50 = trades.slice(0, 50);
    const recent100 = trades.slice(0, 100);
    const prev50 = trades.slice(50, 100);

    const perf = (rows: TradeRow[]) => {
      const tradeCount = rows.length;
      if (!tradeCount) return { tradeCount: 0, net: 0, winRate: 0, expectancy: 0 };
      const rowWins = rows.filter((r) => String(r.outcome ?? r.result).toUpperCase().includes("WIN")).length;
      const rowNet = rows.reduce((acc, row) => acc + num(row.pnl), 0);
      return { tradeCount, net: rowNet, winRate: rowWins / tradeCount, expectancy: rowNet / tradeCount };
    };

    const p50 = perf(recent50);
    const p100 = perf(recent100);
    const pPrev50 = perf(prev50);

    const trendDelta = p50.expectancy - pPrev50.expectancy;
    const trend = trendDelta > 0.05 ? "improving" : trendDelta < -0.05 ? "degrading" : "stable";

    const stateCounts = active.reduce<Record<string, number>>((acc, row) => {
      const key = String(row.strategy_state ?? "candidate").toLowerCase();
      acc[key] = (acc[key] ?? 0) + 1;
      return acc;
    }, {});

    const avgScores = active.reduce(
      (acc, row) => {
        acc.h += num(row.historical_score);
        acc.r += num(row.recent_score);
        acc.c += num(row.combined_score);
        acc.n += 1;
        return acc;
      },
      { h: 0, r: 0, c: 0, n: 0 },
    );

    const warnings: string[] = [];
    if (total < 30) warnings.push(language === "ar" ? "عدد الصفقات قليل جدًا للحكم بثقة." : "Too few trades for stable learning confidence.");
    if (Math.abs(p50.winRate - p100.winRate) > 0.18)
      warnings.push(language === "ar" ? "الأداء غير مستقر بين النوافذ الحديثة." : "Performance is unstable between recent windows.");
    if (maxDrawdown > Math.max(30, Math.abs(net) * 1.1))
      warnings.push(language === "ar" ? "التراجع مرتفع مقارنة بصافي الأداء." : "Drawdown is high relative to net performance.");

    return {
      total,
      wins,
      losses,
      winRate: total ? wins / total : 0,
      lossRate: total ? losses / total : 0,
      net,
      maxDrawdown,
      profitFactor: grossLoss === 0 ? grossProfit : grossProfit / Math.abs(grossLoss),
      expectancy,
      byStrategy,
      bySymbol,
      bestBySymbol,
      p50,
      p100,
      trend,
      stateCounts,
      avgScores: {
        historical: avgScores.n ? avgScores.h / avgScores.n : 0,
        recent: avgScores.n ? avgScores.r / avgScores.n : 0,
        combined: avgScores.n ? avgScores.c / avgScores.n : 0,
      },
      warnings,
    };
  }, [learningCenter, language]);

  useEffect(() => {
    void (async () => {
      try {
        const [history, center, fallback] = await Promise.all([
          fetchHistoryInventory(),
          fetchLearningCenter(),
          fetchHistoricalValidationResults(),
        ]);
        setInventory(history.rows);
        setLearningCenter(center);
        setValidationRows((fallback.rows as ValidationRow[]) ?? []);
      } catch {
        // no-op: panels will use empty defaults
      }
    })();
  }, []);

  async function onFetchHistoricalData() {
    setBusy(true);
    try {
      const result = await fetchHistoricalData(symbol, timeframe, lookbackDays);
      setStatus(result);
      const history = await fetchHistoryInventory();
      setInventory(history.rows);
    } catch (error) {
      setStatus({
        success: false,
        symbol,
        timeframe,
        lookback_days: lookbackDays,
        candles_fetched: 0,
        date_start: "",
        date_end: "",
        storage_path: "",
        status_message: error instanceof Error ? error.message : "Historical fetch failed",
      });
    } finally {
      setBusy(false);
    }
  }

  async function onRunHistoricalValidation() {
    setValidationBusy(true);
    try {
      const result = await runHistoricalValidation();
      const rows = (result.rows as ValidationRow[]) ?? [];
      setValidationRows(rows);
      const center = await fetchLearningCenter();
      setLearningCenter(center);
    } catch {
      const fallback = await fetchHistoricalValidationResults();
      setValidationRows((fallback.rows as ValidationRow[]) ?? []);
    } finally {
      setValidationBusy(false);
    }
  }

  const trendLabel = diagnostics.trend === "improving" ? text.improving : diagnostics.trend === "degrading" ? text.degrading : text.stable;

  return (
    <div className="learning-center">
      <h2>{t("learning.title")}</h2>
      <p>{t("learning.subtitle")}</p>

      <div className="control-grid">
        <label>
          {text.symbol}
          <select value={symbol} onChange={(event) => setSymbol(event.target.value)}>
            {SYMBOLS.map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
        </label>
        <label>
          {text.timeframe}
          <select value={timeframe} onChange={(event) => setTimeframe(event.target.value)}>
            {TIMEFRAMES.map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
        </label>
        <label>
          {text.lookback}
          <select value={lookbackDays} onChange={(event) => setLookbackDays(Number(event.target.value))}>
            {LOOKBACKS.map((item) => (
              <option key={item} value={item}>
                {item} {text.days}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="control-grid">
        <button type="button" onClick={onFetchHistoricalData} disabled={busy}>
          {busy ? text.fetching : text.fetch}
        </button>
        <button type="button" onClick={onRunHistoricalValidation} disabled={validationBusy}>
          {validationBusy ? text.validating : text.validate}
        </button>
      </div>

      <div className={`fetch-status ${statusTone}`}>
        <h3>{text.status}</h3>
        {!status ? (
          <p>{text.noFetch}</p>
        ) : (
          <ul>
            <li>{status.success ? text.success : text.failure}: {status.status_message}</li>
            <li>{text.candles}: {status.candles_fetched}</li>
            <li>{text.dateRange}: {status.date_start || "n/a"} → {status.date_end || "n/a"}</li>
          </ul>
        )}
      </div>

      <div className="diagnostics-grid">
        <div className="diag-card">
          <h3>{text.diagnostics}</h3>
          <ul>
            <li>{text.totalTrades}: <strong>{diagnostics.total}</strong></li>
            <li>{text.winRate}: <strong>{pct(diagnostics.winRate)}</strong></li>
            <li>{text.lossRate}: <strong>{pct(diagnostics.lossRate)}</strong></li>
            <li>{text.netPnl}: <strong>{diagnostics.net.toFixed(2)}</strong></li>
            <li>{text.maxDd}: <strong>{diagnostics.maxDrawdown.toFixed(2)}</strong></li>
            <li>{text.profitFactor}: <strong>{diagnostics.profitFactor.toFixed(2)}</strong></li>
            <li>{text.expectancy}: <strong>{diagnostics.expectancy.toFixed(3)}</strong></li>
          </ul>
        </div>
        <div className="diag-card">
          <h3>{text.learningProgression}</h3>
          <ul>
            <li>{text.last50}: {diagnostics.p50.tradeCount} {text.trades}, {text.netPnl} {diagnostics.p50.net.toFixed(2)}, {text.winRate} {pct(diagnostics.p50.winRate)}</li>
            <li>{text.last100}: {diagnostics.p100.tradeCount} {text.trades}, {text.netPnl} {diagnostics.p100.net.toFixed(2)}, {text.winRate} {pct(diagnostics.p100.winRate)}</li>
            <li>{text.trend}: <span className={`trend ${diagnostics.trend}`}>{trendLabel}</span></li>
          </ul>
        </div>
        <div className="diag-card">
          <h3>{text.strategyStates}</h3>
          <ul>
            <li>{text.active}: {diagnostics.stateCounts.active ?? 0}</li>
            <li>{text.candidate}: {diagnostics.stateCounts.candidate ?? 0}</li>
            <li>{text.probation}: {diagnostics.stateCounts.probation ?? 0}</li>
            <li>{text.disabled}: {diagnostics.stateCounts.disabled ?? 0}</li>
          </ul>
        </div>
        <div className="diag-card">
          <h3>{text.scoreMonitor}</h3>
          <ul>
            <li>{text.historicalScore}: {diagnostics.avgScores.historical.toFixed(2)}</li>
            <li>{text.recentScore}: {diagnostics.avgScores.recent.toFixed(2)}</li>
            <li>{text.combinedScore}: {diagnostics.avgScores.combined.toFixed(2)}</li>
          </ul>
        </div>
      </div>

      <div className="fetch-status warning">
        <h3>{text.warnings}</h3>
        {diagnostics.warnings.length === 0 ? <p>{text.noWarnings}</p> : <ul>{diagnostics.warnings.map((w) => <li key={w}>{w}</li>)}</ul>}
      </div>

      <div>
        <h3>{text.inventory}</h3>
        <table className="inventory-table">
          <thead>
            <tr>
              <th>{text.symbol}</th>
              <th>{text.timeframe}</th>
              <th>{text.candles}</th>
              <th>{text.coveredRange}</th>
            </tr>
          </thead>
          <tbody>
            {inventory.length === 0 ? (
              <tr>
                <td colSpan={4}>{text.noInventory}</td>
              </tr>
            ) : (
              inventory.map((item) => (
                <tr key={`${item.symbol}-${item.timeframe}`}>
                  <td>{item.symbol}</td>
                  <td>{item.timeframe}</td>
                  <td>{item.candles}</td>
                  <td>{item.data_start} → {item.data_end}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div>
        <h3>{text.strategyPerf} — {text.perStrategy}</h3>
        <table className="inventory-table">
          <thead><tr><th>{text.strategy}</th><th>{text.trades}</th><th>{text.winRate}</th><th>{text.netPnl}</th></tr></thead>
          <tbody>
            {diagnostics.byStrategy.length === 0 ? <tr><td colSpan={4}>-</td></tr> : diagnostics.byStrategy.map((item) => (
              <tr key={item.strategy}><td>{item.strategy}</td><td>{item.trades}</td><td>{pct(item.winRate)}</td><td>{item.net.toFixed(2)}</td></tr>
            ))}
          </tbody>
        </table>
      </div>

      <div>
        <h3>{text.strategyPerf} — {text.perSymbol}</h3>
        <table className="inventory-table">
          <thead><tr><th>{text.symbol}</th><th>{text.trades}</th><th>{text.winRate}</th><th>{text.netPnl}</th></tr></thead>
          <tbody>
            {diagnostics.bySymbol.length === 0 ? <tr><td colSpan={4}>-</td></tr> : diagnostics.bySymbol.map((item) => (
              <tr key={item.symbol}><td>{item.symbol}</td><td>{item.trades}</td><td>{pct(item.winRate)}</td><td>{item.net.toFixed(2)}</td></tr>
            ))}
          </tbody>
        </table>
      </div>

      <div>
        <h3>{text.bestPerSymbol}</h3>
        <table className="inventory-table">
          <thead><tr><th>{text.symbol}</th><th>{text.strategy}</th><th>{text.combinedScore}</th></tr></thead>
          <tbody>
            {diagnostics.bestBySymbol.length === 0 ? <tr><td colSpan={3}>-</td></tr> : diagnostics.bestBySymbol.map((item) => (
              <tr key={item.symbol}><td>{item.symbol}</td><td>{item.strategy}</td><td>{item.score.toFixed(2)}</td></tr>
            ))}
          </tbody>
        </table>
      </div>

      <div>
        <h3>{text.validation}</h3>
        <table className="inventory-table">
          <thead>
            <tr>
              <th>{text.symbol}</th><th>TF</th><th>{text.strategy}</th><th>{text.rank}</th><th>{text.trades}</th><th>{text.winRate}</th><th>{text.lossRate}</th><th>{text.netPnl}</th><th>{text.maxDd}</th><th>PF</th><th>{text.expectancy}</th><th>Avg R/R</th><th>{text.score}</th>
            </tr>
          </thead>
          <tbody>
            {validationRows.length === 0 ? <tr><td colSpan={13}>{text.noValidation}</td></tr> : validationRows.map((item, index) => (
              <tr key={`${item.symbol}-${item.timeframe}-${item.strategy}-${index}`}>
                <td>{item.symbol ?? "-"}</td><td>{item.timeframe ?? "-"}</td><td>{item.strategy ?? "-"}</td><td>{item.rank ?? "-"}</td><td>{item.total_trades ?? "-"}</td><td>{typeof item.win_rate === "number" ? item.win_rate.toFixed(3) : "-"}</td><td>{typeof item.loss_rate === "number" ? item.loss_rate.toFixed(3) : "-"}</td><td>{typeof item.net_pnl === "number" ? item.net_pnl.toFixed(2) : "-"}</td><td>{typeof item.max_drawdown === "number" ? item.max_drawdown.toFixed(2) : "-"}</td><td>{typeof item.profit_factor === "number" ? item.profit_factor.toFixed(3) : "-"}</td><td>{typeof item.expectancy === "number" ? item.expectancy.toFixed(3) : "-"}</td><td>{typeof item.avg_reward_risk === "number" ? item.avg_reward_risk.toFixed(3) : "-"}</td><td>{typeof item.final_validation_score === "number" ? item.final_validation_score.toFixed(2) : typeof item.score === "number" ? item.score.toFixed(2) : "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div>
        <h3>{text.ranked}</h3>
        <table className="inventory-table">
          <thead><tr><th>{text.symbol}</th><th>TF</th><th>{text.strategy}</th><th>{text.rank}</th><th>{text.score}</th></tr></thead>
          <tbody>
            {rankedStrategies.length === 0 ? <tr><td colSpan={5}>{text.noRanked}</td></tr> : rankedStrategies.map((item, index) => (
              <tr key={`ranked-${item.symbol}-${item.timeframe}-${item.strategy}-${index}`}>
                <td>{item.symbol ?? "-"}</td><td>{item.timeframe ?? "-"}</td><td>{item.strategy ?? "-"}</td><td>{item.rank ?? "-"}</td><td>{typeof item.final_validation_score === "number" ? item.final_validation_score.toFixed(2) : "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div>
        <h3>{text.topParams}</h3>
        <table className="inventory-table">
          <thead><tr><th>{text.symbol}</th><th>TF</th><th>{text.strategy}</th><th>{text.params}</th><th>{text.score}</th></tr></thead>
          <tbody>
            {topParameterSets.length === 0 ? <tr><td colSpan={5}>{text.noParams}</td></tr> : topParameterSets.map((item, index) => (
              <tr key={`params-${item.symbol}-${item.timeframe}-${item.strategy}-${index}`}>
                <td>{item.symbol ?? "-"}</td><td>{item.timeframe ?? "-"}</td><td>{item.strategy ?? "-"}</td><td>{item.params ?? "-"}</td><td>{typeof item.final_validation_score === "number" ? item.final_validation_score.toFixed(2) : "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
