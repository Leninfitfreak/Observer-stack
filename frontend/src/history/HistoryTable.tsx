import type { IncidentAnalysis } from "../types";

type SortDirection = "asc" | "desc";

interface Props {
  incidents: IncidentAnalysis[];
  total: number;
  limit: number;
  offset: number;
  sortDirection: SortDirection;
  onSortToggle: () => void;
  onPageChange: (offset: number) => void;
  onView: (incident: IncidentAnalysis) => void;
}

function classificationClass(classification: string): string {
  const lower = classification.toLowerCase();
  if (lower.includes("false")) return "badge-gray";
  if (lower.includes("performance")) return "badge-yellow";
  if (lower.includes("infra")) return "badge-red";
  if (lower.includes("observability")) return "badge-blue";
  return "badge-default";
}

function mitigationText(incident: IncidentAnalysis): string {
  const actions = incident.mitigation?.actions;
  if (Array.isArray(actions) && actions.length > 0) {
    return String(actions[0]);
  }
  return "-";
}

function mitigationIcon(value: boolean | undefined): string {
  if (value === true) return "🟢";
  if (value === false) return "🔴";
  return "⚪";
}

export function HistoryTable({
  incidents,
  total,
  limit,
  offset,
  sortDirection,
  onSortToggle,
  onPageChange,
  onView,
}: Props) {
  const page = Math.floor(offset / limit) + 1;
  const totalPages = Math.max(1, Math.ceil(total / limit));
  const canPrev = offset > 0;
  const canNext = offset + limit < total;

  return (
    <div className="history-table-wrap">
      <table className="history-table">
        <thead>
          <tr>
            <th className="sortable" onClick={onSortToggle}>
              Timestamp {sortDirection === "desc" ? "↓" : "↑"}
            </th>
            <th>Service</th>
            <th>Classification</th>
            <th>Anomaly Score</th>
            <th>Confidence</th>
            <th>Risk Forecast</th>
            <th>Mitigation Suggested</th>
            <th>Mitigation Success</th>
            <th>View</th>
          </tr>
        </thead>
        <tbody>
          {incidents.length === 0 ? (
            <tr>
              <td colSpan={9} className="empty-row">
                No incidents found for selected filters.
              </td>
            </tr>
          ) : (
            incidents.map((incident) => (
              <tr key={incident.id}>
                <td>{new Date(incident.created_at).toLocaleString()}</td>
                <td>{incident.service_name}</td>
                <td>
                  <span className={`badge ${classificationClass(incident.classification)}`}>{incident.classification}</span>
                </td>
                <td>{incident.anomaly_score.toFixed(2)}</td>
                <td>{Math.round(incident.confidence_score * 100)}%</td>
                <td>{Math.round(incident.risk_forecast * 100)}%</td>
                <td>{mitigationText(incident)}</td>
                <td>{mitigationIcon(incident.mitigation_success)}</td>
                <td>
                  <button className="view-btn" onClick={() => onView(incident)}>
                    View
                  </button>
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>

      <div className="pagination">
        <button onClick={() => canPrev && onPageChange(Math.max(0, offset - limit))} disabled={!canPrev}>
          Prev
        </button>
        <span>
          Page {page} / {totalPages}
        </span>
        <button onClick={() => canNext && onPageChange(offset + limit)} disabled={!canNext}>
          Next
        </button>
      </div>
    </div>
  );
}
