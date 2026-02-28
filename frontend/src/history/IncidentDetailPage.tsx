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
  const supportingSignals = useMemo(() => (latestAnalysis?.supporting_signals as Record<string, unknown> | undefined) ?? {}, [latestAnalysis]);
  const confidenceBreakdown = useMemo(() => (latestAnalysis?.confidence_breakdown as Record<string, unknown> | undefined) ?? {}, [latestAnalysis]);
  const fallbackTelemetry = useMemo(() => {
    const fromSnapshot = (latestMetrics?.raw_metrics_json as Record<string, unknown> | undefined) ?? {};
    const fromMitigation = (latestAnalysis?.mitigation?.telemetry as Record<string, unknown> | undefined) ?? {};
    const fromPayload = (data?.incident?.raw_payload?.metrics as Record<string, unknown> | undefined) ?? {};
    return { ...fromPayload, ...fromMitigation, ...fromSnapshot };
  }, [data, latestAnalysis, latestMetrics]);

  const cpuPercent = useMemo(() => {
    const snapshotValue = Number(latestMetrics?.cpu_usage);
    if (Number.isFinite(snapshotValue) && snapshotValue > 0) return snapshotValue;
    const raw = Number(fallbackTelemetry?.cpu_usage ?? 0);
    if (!Number.isFinite(raw)) return 0;
    return raw <= 1 ? raw * 100 : raw;
  }, [latestMetrics, fallbackTelemetry]);

  const memoryMb = useMemo(() => {
    const snapshotValue = Number(latestMetrics?.memory_usage);
    if (Number.isFinite(snapshotValue) && snapshotValue > 0) return snapshotValue;
    const raw = Number(fallbackTelemetry?.memory_usage ?? 0);
    if (!Number.isFinite(raw)) return 0;
    return raw > 1024 ? raw / (1024 * 1024) : raw;
  }, [latestMetrics, fallbackTelemetry]);

  const requestRate = useMemo(() => Number(fallbackTelemetry?.request_rate ?? 0), [fallbackTelemetry]);
  const podRestarts = useMemo(() => Number(fallbackTelemetry?.pod_restarts ?? 0), [fallbackTelemetry]);

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
              {renderList(supportingSignals).map((signal) => (
                <li key={signal}>{signal}</li>
              ))}
            </ul>
          </div>

          <div className="detail-card">
            <h3>Supporting Evidence</h3>
            <ul>
              {renderList((supportingSignals as Record<string, unknown>)?.evidence).map((evidence) => (
                <li key={evidence}>{evidence}</li>
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
            <pre>{JSON.stringify(confidenceBreakdown || {}, null, 2)}</pre>
          </div>

          <div className="detail-card">
            <h3>Correlated Signals</h3>
            <pre>{JSON.stringify((supportingSignals as Record<string, unknown>)?.correlation || {}, null, 2)}</pre>
          </div>

          <div className="detail-card">
            <h3>Causal Analysis</h3>
            <pre>{JSON.stringify((supportingSignals as Record<string, unknown>)?.causal_analysis || {}, null, 2)}</pre>
          </div>

          <div className="detail-card">
            <h3>Topology Insights</h3>
            <pre>{JSON.stringify((supportingSignals as Record<string, unknown>)?.topology_insights || {}, null, 2)}</pre>
          </div>

          <div className="detail-card">
            <h3>Metrics Snapshot</h3>
            <ul>
              <li>CPU Usage: {cpuPercent.toFixed(2)}%</li>
              <li>Memory Usage: {Math.round(memoryMb)} MB</li>
              <li>Latency P95: {Math.round(Number(latestMetrics?.latency_p95 || 0))} ms</li>
              <li>Error Rate: {Number(latestMetrics?.error_rate || 0).toFixed(2)}%</li>
              <li>Request Rate: {Number.isFinite(requestRate) ? requestRate.toFixed(4) : "0.0000"} rps</li>
              <li>Pod Restarts: {Number.isFinite(podRestarts) ? podRestarts.toFixed(0) : "0"}</li>
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
