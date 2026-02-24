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
  onView: (incidentId: string) => void;
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
  return incident.root_cause || "-";
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
              Timestamp {sortDirection === "desc" ? "?" : "?"}
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
              <tr key={incident.incident_id}>
                <td>{new Date(incident.created_at).toLocaleString()}</td>
                <td>{incident.affected_services}</td>
                <td>
                  <span className={`badge ${classificationClass(incident.classification || "Unknown")}`}>
                    {incident.classification || "Unknown"}
                  </span>
                </td>
                <td>-</td>
                <td>{Math.round((incident.confidence_score || 0) * 100)}%</td>
                <td>{Math.round((incident.risk_forecast || 0) * 100)}%</td>
                <td>{mitigationText(incident)}</td>
                <td>N/A</td>
                <td>
                  <button className="view-btn" onClick={() => onView(incident.incident_id)}>
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
