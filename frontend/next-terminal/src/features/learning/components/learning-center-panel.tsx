"use client";

import { useMemo, useState } from "react";

import {
  fetchHistoricalData,
  fetchHistoryInventory,
  type HistoricalFetchPayload,
  type HistoryInventoryPayload,
} from "@/features/learning/api/learning";

const SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"];
const TIMEFRAMES = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"];
const LOOKBACKS = [30, 90, 180, 365];

export function LearningCenterPanel() {
  const [symbol, setSymbol] = useState("EURUSD");
  const [timeframe, setTimeframe] = useState("M5");
  const [lookbackDays, setLookbackDays] = useState(90);
  const [status, setStatus] = useState<HistoricalFetchPayload | null>(null);
  const [inventory, setInventory] = useState<HistoryInventoryPayload["rows"]>([]);
  const [busy, setBusy] = useState(false);

  const statusTone = useMemo(() => {
    if (!status) return "idle";
    return status.success ? "ok" : "error";
  }, [status]);

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

      <button type="button" onClick={onFetchHistoricalData} disabled={busy}>
        {busy ? "Fetching..." : "Fetch Historical Data"}
      </button>

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
    </div>
  );
}
