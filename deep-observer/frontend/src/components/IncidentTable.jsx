import { Fragment } from "react";

export default function IncidentTable({ incidents = [], selectedIncidentId, onSelectIncident, onOpenIncident, emptyHint = "" }) {
  const safeIncidents = Array.isArray(incidents) ? incidents : [];
  return (
    <section className="rounded-3xl border border-white/10 bg-slate-900/60 p-6">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white">Incident Table</h2>
        <span className="text-sm text-slate-400">{safeIncidents.length} incidents</span>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full text-left text-sm text-slate-300">
          <thead className="text-xs uppercase tracking-[0.3em] text-slate-500">
            <tr>
              <th className="pb-3">Service</th>
              <th className="pb-3">Cluster</th>
              <th className="pb-3">Namespace</th>
              <th className="pb-3">Severity</th>
              <th className="pb-3">Type</th>
              <th className="pb-3">Timestamp</th>
              <th className="pb-3">Anomaly Score</th>
              <th className="pb-3">Signals</th>
              <th className="pb-3">Root Cause</th>
              <th className="pb-3">Impacted</th>
            </tr>
          </thead>
          <tbody>
            {safeIncidents.length === 0 ? (
              <tr className="border-t border-white/5">
                <td className="py-6 text-slate-400" colSpan={10}>
                  {emptyHint || "No incidents in this time range."}
                </td>
              </tr>
            ) : null}
            {safeIncidents.map((incident) => {
              const expanded = selectedIncidentId === incident.incident_id;
              const handleOpen = () => {
                if (typeof onOpenIncident === "function") {
                  onOpenIncident(incident.incident_id);
                  return;
                }
                if (typeof onSelectIncident === "function") {
                  onSelectIncident(incident.incident_id, { scroll: true });
                }
              };
              return (
                <Fragment key={incident.incident_id}>
                  <tr
                    className={`cursor-pointer border-t border-white/5 transition hover:bg-white/5 ${
                      expanded ? "bg-white/7" : ""
                    }`}
                    onClick={handleOpen}
                  >
                    <td className="py-4">
                      <div className="flex flex-col gap-1">
                        <button
                          type="button"
                          className="w-fit text-left font-medium text-white hover:text-cyan-300"
                          onClick={(event) => {
                            event.stopPropagation();
                            handleOpen();
                          }}
                        >
                          {incident.service}
                        </button>
                        <span className="text-xs text-slate-500">{incident.problem_id}</span>
                      </div>
                    </td>
                    <td>{incident.cluster}</td>
                    <td>{incident.namespace}</td>
                    <td>
                      <SeverityBadge severity={incident.severity} />
                    </td>
                    <td>{toText(incident.incident_type || "observed")}</td>
                    <td>{new Date(incident.timestamp).toLocaleString()}</td>
                    <td>{formatScore(incident.anomaly_score)}</td>
                    <td>{toList(incident.signals).join(", ")}</td>
                    <td>{toText(incident.root_cause_entity || incident.reasoning?.root_cause_service || "Pending")}</td>
                    <td>{formatImpactedServices(incident.impacts)}</td>
                  </tr>
                  {expanded ? (
                    <tr className="border-b border-white/5 bg-slate-950/40">
                      <td colSpan={10} className="px-4 py-3 text-xs text-slate-300">
                        <div className="grid gap-2 md:grid-cols-3">
                          <div>
                            <p className="mb-1 uppercase tracking-[0.2em] text-slate-500">Signals</p>
                            <p>{toList(incident.signals).join(", ") || "N/A"}</p>
                          </div>
                          <div>
                            <p className="mb-1 uppercase tracking-[0.2em] text-slate-500">Dependency Chain</p>
                            <p>{toList(incident.dependency_chain).join(" -> ") || "N/A"}</p>
                          </div>
                          <div>
                            <p className="mb-1 uppercase tracking-[0.2em] text-slate-500">Suggested Actions</p>
                            <p>{toList(incident.remediation_suggestions).slice(0, 3).join(" | ") || "N/A"}</p>
                          </div>
                        </div>
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function SeverityBadge({ severity }) {
  const tone =
    severity === "critical"
      ? "bg-rose-500/20 text-rose-300"
      : severity === "high"
        ? "bg-orange-500/20 text-orange-300"
        : "bg-amber-500/20 text-amber-200";
  return <span className={`rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] ${tone}`}>{severity}</span>;
}

function formatScore(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "0.00";
  return numeric.toFixed(2);
}

function toList(value) {
  if (Array.isArray(value)) return value.map((item) => String(item));
  if (value === null || value === undefined || value === "") return [];
  return [String(value)];
}

function formatImpactedServices(value) {
  if (!Array.isArray(value) || value.length === 0) return "";
  return value
    .map((item) => {
      if (typeof item === "string") return item;
      if (item && typeof item === "object") return toText(item.service);
      return "";
    })
    .filter(Boolean)
    .slice(0, 3)
    .join(", ");
}

function toText(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}
