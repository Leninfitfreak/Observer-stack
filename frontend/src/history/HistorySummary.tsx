import type { IncidentSummaryResponse } from "../types";

interface Props {
  summary: IncidentSummaryResponse | null;
}

function mostCommonClassification(distribution: Record<string, number>): string {
  const entries = Object.entries(distribution);
  if (entries.length === 0) {
    return "-";
  }
  return entries.sort((a, b) => b[1] - a[1])[0][0];
}

export function HistorySummary({ summary }: Props) {
  const commonClassification = summary ? mostCommonClassification(summary.classification_distribution) : "-";
  const topMitigation = summary?.top_mitigation || "-";
  const avgConfidence = summary ? `${Math.round(summary.avg_confidence_score * 100)}%` : "-";

  return (
    <div className="summary-grid">
      <div className="summary-card">
        <p>Total Incidents</p>
        <h3>{summary?.total_incidents ?? "-"}</h3>
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
