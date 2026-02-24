import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { fetchIncidentDetails } from "./api";
import type { IncidentDetailResponse } from "../types";
import "./history.css";

function renderList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((item) => String(item));
  }
  if (value && typeof value === "object") {
    const nested = (value as Record<string, unknown>).signals || (value as Record<string, unknown>).actions;
    if (Array.isArray(nested)) {
      return nested.map((item) => String(item));
    }
  }
  return [];
}

export default function IncidentDetailPage() {
  const { incidentId = "" } = useParams<{ incidentId: string }>();
  const [data, setData] = useState<IncidentDetailResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showRaw, setShowRaw] = useState(false);

  useEffect(() => {
    if (!incidentId) return;
    setLoading(true);
    setError(null);
    fetchIncidentDetails(incidentId)
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load incident"))
      .finally(() => setLoading(false));
  }, [incidentId]);

  const latestAnalysis = useMemo(() => data?.analysis?.[0] ?? null, [data]);
  const latestMetrics = useMemo(() => data?.metrics_snapshot?.[0] ?? null, [data]);

  return (
    <main className="history-page">
      <nav className="top-nav">
        <a href="/dashboard">Dashboard</a>
        <a href="/history" className="active">Incident History</a>
      </nav>

      <header className="history-header">
        <h1>Incident Drilldown</h1>
        <p className="detail-subtitle">{incidentId}</p>
      </header>

      {loading && <div className="status">Loading incident details...</div>}
      {error && <div className="status error">{error}</div>}

      {!loading && !error && data && (
        <section className="detail-layout">
          <div className="detail-card">
            <h3>Executive Summary</h3>
            <p>{latestAnalysis?.executive_summary || "-"}</p>
          </div>

          <div className="detail-card">
            <h3>Root Cause</h3>
            <p>{latestAnalysis?.root_cause || "-"}</p>
          </div>

          <div className="detail-card">
            <h3>Supporting Signals</h3>
            <ul>
              {renderList(latestAnalysis?.supporting_signals).map((signal) => (
                <li key={signal}>{signal}</li>
              ))}
            </ul>
          </div>

          <div className="detail-card split-two">
            <div>
              <h3>Risk Forecast</h3>
              <p>{Math.round(Number(latestAnalysis?.risk_forecast || 0) * 100)}%</p>
            </div>
            <div>
              <h3>Confidence</h3>
              <p>{Math.round(Number(latestAnalysis?.confidence_score || 0) * 100)}%</p>
            </div>
          </div>

          <div className="detail-card">
            <h3>Confidence Breakdown</h3>
            <pre>{JSON.stringify(latestAnalysis?.confidence_breakdown || {}, null, 2)}</pre>
          </div>

          <div className="detail-card">
            <h3>Metrics Snapshot</h3>
            <ul>
              <li>CPU Usage: {Number(latestMetrics?.cpu_usage || 0).toFixed(2)}%</li>
              <li>Memory Usage: {Math.round(Number(latestMetrics?.memory_usage || 0))} MB</li>
              <li>Latency P95: {Math.round(Number(latestMetrics?.latency_p95 || 0))} ms</li>
              <li>Error Rate: {Number(latestMetrics?.error_rate || 0).toFixed(2)}%</li>
              <li>Thread Pool Saturation: {Number(latestMetrics?.thread_pool_saturation || 0).toFixed(2)}</li>
            </ul>
          </div>

          <details className="detail-card raw-block" open={false}>
            <summary>Raw JSON</summary>
            <button className="raw-toggle" onClick={() => setShowRaw((prev) => !prev)}>
              {showRaw ? "Hide Raw JSON" : "Show Raw JSON"}
            </button>
            {showRaw && <pre>{JSON.stringify(data, null, 2)}</pre>}
          </details>
        </section>
      )}
    </main>
  );
}
