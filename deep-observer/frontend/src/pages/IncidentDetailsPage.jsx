import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { fetchIncident } from "../api";
import IncidentDetailsPanel from "../components/IncidentDetailsPanel";

export default function IncidentDetailsPage() {
  const { incidentId } = useParams();
  const [incident, setIncident] = useState(null);

  useEffect(() => {
    let cancelled = false;
    fetchIncident(incidentId)
      .then((payload) => {
        if (!cancelled) {
          setIncident(payload && typeof payload === "object" ? payload : null);
        }
      })
      .catch(console.error);
    return () => {
      cancelled = true;
    };
  }, [incidentId]);

  const filterQuery = useMemo(() => {
    if (!incident) {
      return {};
    }
    const scope = incident.scope && typeof incident.scope === "object" ? incident.scope : {};
    const end = scope.incident_window_end || incident.telemetry_snapshot?.incident_window_end || new Date(incident.timestamp).toISOString();
    const start =
      scope.incident_window_start ||
      incident.telemetry_snapshot?.incident_window_start ||
      new Date(new Date(incident.timestamp).getTime() - 60 * 60 * 1000).toISOString();
    return {
      cluster: scope.cluster || incident.cluster || "",
      namespace: scope.namespace || incident.namespace || "",
      service: scope.service || incident.service || "",
      start,
      end,
    };
  }, [incident]);

  return (
    <main className="mx-auto min-h-screen w-full max-w-[1400px] space-y-6 px-6 py-8">
      <Link className="text-sm text-cyan-300 hover:text-cyan-200" to="/">
        Back to dashboard
      </Link>
      <IncidentDetailsPanel incident={incident} filterQuery={filterQuery} />
    </main>
  );
}
