import type { IncidentSummaryResponse } from "../types";

interface Props {
  summary: IncidentSummaryResponse | null;
}

export function HistorySummary({ summary }: Props) {
  const commonClassification = summary?.mostCommonClassification || "-";
  const topMitigation = summary?.topMitigation || "-";
  const avgConfidence = summary ? `${Math.round(summary.avgConfidence * 100)}%` : "-";

  return (
    <div className="summary-grid">
      <div className="summary-card">
        <p>Total Incidents</p>
        <h3>{summary?.totalIncidents ?? "-"}</h3>
      </div>
      <div className="summary-card">
        <p>Avg Confidence</p>
        <h3>{avgConfidence}</h3>
      </div>
      <div className="summary-card">
        <p>Most Common Classification</p>
        <h3>{commonClassification}</h3>
      </div>
      <div className="summary-card">
        <p>Top Mitigation</p>
        <h3>{topMitigation}</h3>
      </div>
    </div>
  );
}
