import { useEffect, useState } from "react";
import { fetchIncidentAnalysis } from "./api";
import type { IncidentAnalysis } from "../types";

interface Props {
  incident: IncidentAnalysis | null;
  open: boolean;
  onClose: () => void;
}

function confidenceBreakdown(mitigation: any): string[] {
  const breakdown = mitigation?.confidence_breakdown;
  if (!breakdown || typeof breakdown !== "object") {
    return [];
  }
  return Object.entries(breakdown).map(([k, v]) => `${k}: ${v}`);
}

function listFromValue(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.map((item) => String(item));
}

export function IncidentDetailDrawer({ incident, open, onClose }: Props) {
  const [showRaw, setShowRaw] = useState(false);
  const [similar, setSimilar] = useState<IncidentAnalysis[]>([]);
  const [loadingSimilar, setLoadingSimilar] = useState(false);

  useEffect(() => {
    if (!incident || !open) {
      return;
    }
    const fetchSimilar = async () => {
      setLoadingSimilar(true);
      try {
        const min = Math.max(0, incident.anomaly_score - 0.1);
        const max = Math.min(1, incident.anomaly_score + 0.1);
        const start = new Date(Date.now() - 1000 * 60 * 60 * 24 * 365).toISOString().slice(0, 10);
        const end = new Date().toISOString().slice(0, 10);
        const res = await fetchIncidentAnalysis({
          start_date: start,
          end_date: end,
          service_name: incident.service_name,
          anomaly_score_min: min,
          anomaly_score_max: max,
          limit: 3,
          offset: 0,
        });
        setSimilar(res.items.filter((item) => item.id !== incident.id).slice(0, 3));
      } catch {
        setSimilar([]);
      } finally {
        setLoadingSimilar(false);
      }
    };
    fetchSimilar();
  }, [incident, open]);

  if (!open || !incident) {
    return null;
  }

  const supportingSignals = listFromValue(incident.mitigation?.supporting_signals);
  const actions = listFromValue(incident.mitigation?.actions);
  const confidence = confidenceBreakdown(incident.mitigation);

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <aside className="drawer" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-header">
          <h3>Incident Details</h3>
          <button onClick={onClose}>Close</button>
        </div>
        <section>
          <h4>Executive Summary</h4>
          <p>{incident.mitigation?.executive_summary || "-"}</p>
        </section>
        <section>
          <h4>Root Cause</h4>
          <p>{incident.root_cause}</p>
        </section>
        <section>
          <h4>Supporting Signals</h4>
          <ul>
            {supportingSignals.length === 0 ? <li>-</li> : supportingSignals.map((signal) => <li key={signal}>{signal}</li>)}
          </ul>
        </section>
        <section>
          <h4>Risk Forecast</h4>
          <p>{Math.round(incident.risk_forecast * 100)}%</p>
        </section>
        <section>
          <h4>Confidence Breakdown</h4>
          <ul>
            {confidence.length === 0 ? <li>-</li> : confidence.map((item) => <li key={item}>{item}</li>)}
          </ul>
        </section>
        <section>
          <h4>Suggested Mitigations</h4>
          <ul>{actions.length === 0 ? <li>-</li> : actions.map((action) => <li key={action}>{action}</li>)}</ul>
        </section>
        <section>
          <h4>Similar Historical Incidents</h4>
          {loadingSimilar ? (
            <p>Loading...</p>
          ) : similar.length === 0 ? (
            <p>No similar incidents found.</p>
          ) : (
            <ul>
              {similar.map((item) => (
                <li key={item.id}>
                  {new Date(item.created_at).toLocaleString()} | {item.service_name} | score {item.anomaly_score.toFixed(2)}
                </li>
              ))}
            </ul>
          )}
        </section>
        <section>
          <button className="raw-toggle" onClick={() => setShowRaw((prev) => !prev)}>
            {showRaw ? "Hide Raw JSON" : "Show Raw JSON"}
          </button>
          {showRaw && <pre className="raw-json">{JSON.stringify(incident, null, 2)}</pre>}
        </section>
      </aside>
    </div>
  );
}
