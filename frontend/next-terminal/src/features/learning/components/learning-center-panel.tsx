"use client";

import { useMemo, useState } from "react";

import {
  fetchHistoricalData,
  fetchHistoryInventory,
  fetchHistoricalValidationResults,
  runHistoricalValidation,
  type HistoricalFetchPayload,
  type HistoryInventoryPayload,
} from "@/features/learning/api/learning";

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

export function LearningCenterPanel() {
  const [symbol, setSymbol] = useState("EURUSD");
  const [timeframe, setTimeframe] = useState("M5");
  const [lookbackDays, setLookbackDays] = useState(90);
  const [status, setStatus] = useState<HistoricalFetchPayload | null>(null);
  const [inventory, setInventory] = useState<HistoryInventoryPayload["rows"]>([]);
  const [validationRows, setValidationRows] = useState<ValidationRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [validationBusy, setValidationBusy] = useState(false);

  const statusTone = useMemo(() => {
    if (!status) return "idle";
    return status.success ? "ok" : "error";
  }, [status]);

  const rankedStrategies = useMemo(() => {
    return [...validationRows].sort(
      (a, b) => Number(b.final_validation_score ?? b.score ?? 0) - Number(a.final_validation_score ?? a.score ?? 0),
    );
  }, [validationRows]);

  const topParameterSets = useMemo(() => {
    const winners = validationRows.filter((row) => row.best_in_symbol_timeframe);
    return winners.length > 0 ? winners : rankedStrategies.slice(0, 10);
  }, [rankedStrategies, validationRows]);

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
      if (rows.length === 0) {
        const fallback = await fetchHistoricalValidationResults();
        setValidationRows((fallback.rows as ValidationRow[]) ?? []);
      }
    } catch {
      const fallback = await fetchHistoricalValidationResults();
      setValidationRows((fallback.rows as ValidationRow[]) ?? []);
    } finally {
      setValidationBusy(false);
    }
  }

  return (
    <div className="learning-center">
      <h2>Self-Learning Center</h2>
      <p>Historical MT5 data ingestion for local-first model learning and validation.</p>

      <div className="control-grid">
        <label>
          Symbol
          <select value={symbol} onChange={(event) => setSymbol(event.target.value)}>
            {SYMBOLS.map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
        </label>
        <label>
          Timeframe
          <select value={timeframe} onChange={(event) => setTimeframe(event.target.value)}>
            {TIMEFRAMES.map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
        </label>
        <label>
          Lookback Range
          <select value={lookbackDays} onChange={(event) => setLookbackDays(Number(event.target.value))}>
            {LOOKBACKS.map((item) => (
              <option key={item} value={item}>
                {item} days
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="control-grid">
        <button type="button" onClick={onFetchHistoricalData} disabled={busy}>
          {busy ? "Fetching..." : "Fetch Historical Data"}
        </button>
        <button type="button" onClick={onRunHistoricalValidation} disabled={validationBusy}>
          {validationBusy ? "Validating..." : "Run Historical Validation"}
        </button>
      </div>

      <div className={`fetch-status ${statusTone}`}>
        <h3>Status</h3>
        {!status ? (
          <p>No historical fetch executed yet.</p>
        ) : (
          <ul>
            <li>{status.success ? "Success" : "Failure"}: {status.status_message}</li>
            <li>Candles fetched: {status.candles_fetched}</li>
            <li>Date range: {status.date_start || "n/a"} → {status.date_end || "n/a"}</li>
          </ul>
        )}
      </div>

      <div>
        <h3>History Inventory</h3>
        <table className="inventory-table">
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Timeframe</th>
              <th>Candles</th>
              <th>Covered Range</th>
            </tr>
          </thead>
          <tbody>
            {inventory.length === 0 ? (
              <tr>
                <td colSpan={4}>No stored historical datasets yet.</td>
              </tr>
            ) : (
              inventory.map((item) => (
                <tr key={`${item.symbol}-${item.timeframe}`}>
                  <td>{item.symbol}</td>
                  <td>{item.timeframe}</td>
                  <td>{item.candles}</td>
                  <td>
                    {item.data_start} → {item.data_end}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div>
        <h3>Historical Validation Results</h3>
        <table className="inventory-table">
          <thead>
            <tr>
              <th>Symbol</th>
              <th>TF</th>
              <th>Strategy</th>
              <th>Rank</th>
              <th>Trades</th>
              <th>Win Rate</th>
              <th>Loss Rate</th>
              <th>Net PnL</th>
              <th>Max DD</th>
              <th>PF</th>
              <th>Expectancy</th>
              <th>Avg R/R</th>
              <th>Score</th>
            </tr>
          </thead>
          <tbody>
            {validationRows.length === 0 ? (
              <tr>
                <td colSpan={13}>No validation results yet. Run historical validation.</td>
              </tr>
            ) : (
              validationRows.map((item, index) => (
                <tr key={`${item.symbol}-${item.timeframe}-${item.strategy}-${index}`}>
                  <td>{item.symbol ?? "-"}</td>
                  <td>{item.timeframe ?? "-"}</td>
                  <td>{item.strategy ?? "-"}</td>
                  <td>{item.rank ?? "-"}</td>
                  <td>{item.total_trades ?? "-"}</td>
                  <td>{typeof item.win_rate === "number" ? item.win_rate.toFixed(3) : "-"}</td>
                  <td>{typeof item.loss_rate === "number" ? item.loss_rate.toFixed(3) : "-"}</td>
                  <td>{typeof item.net_pnl === "number" ? item.net_pnl.toFixed(2) : "-"}</td>
                  <td>{typeof item.max_drawdown === "number" ? item.max_drawdown.toFixed(2) : "-"}</td>
                  <td>{typeof item.profit_factor === "number" ? item.profit_factor.toFixed(3) : "-"}</td>
                  <td>{typeof item.expectancy === "number" ? item.expectancy.toFixed(3) : "-"}</td>
                  <td>{typeof item.avg_reward_risk === "number" ? item.avg_reward_risk.toFixed(3) : "-"}</td>
                  <td>
                    {typeof item.final_validation_score === "number"
                      ? item.final_validation_score.toFixed(2)
                      : typeof item.score === "number"
                        ? item.score.toFixed(2)
                        : "-"}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div>
        <h3>Ranked Strategies</h3>
        <table className="inventory-table">
          <thead>
            <tr>
              <th>Symbol</th>
              <th>TF</th>
              <th>Strategy</th>
              <th>Rank</th>
              <th>Final Score</th>
            </tr>
          </thead>
          <tbody>
            {rankedStrategies.length === 0 ? (
              <tr>
                <td colSpan={5}>No ranked strategies yet.</td>
              </tr>
            ) : (
              rankedStrategies.map((item, index) => (
                <tr key={`ranked-${item.symbol}-${item.timeframe}-${item.strategy}-${index}`}>
                  <td>{item.symbol ?? "-"}</td>
                  <td>{item.timeframe ?? "-"}</td>
                  <td>{item.strategy ?? "-"}</td>
                  <td>{item.rank ?? "-"}</td>
                  <td>{typeof item.final_validation_score === "number" ? item.final_validation_score.toFixed(2) : "-"}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div>
        <h3>Top Parameter Sets</h3>
        <table className="inventory-table">
          <thead>
            <tr>
              <th>Symbol</th>
              <th>TF</th>
              <th>Strategy</th>
              <th>Params</th>
              <th>Final Score</th>
            </tr>
          </thead>
          <tbody>
            {topParameterSets.length === 0 ? (
              <tr>
                <td colSpan={5}>No parameter sets yet.</td>
              </tr>
            ) : (
              topParameterSets.map((item, index) => (
                <tr key={`params-${item.symbol}-${item.timeframe}-${item.strategy}-${index}`}>
                  <td>{item.symbol ?? "-"}</td>
                  <td>{item.timeframe ?? "-"}</td>
                  <td>{item.strategy ?? "-"}</td>
                  <td>{item.params ?? "-"}</td>
                  <td>{typeof item.final_validation_score === "number" ? item.final_validation_score.toFixed(2) : "-"}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
