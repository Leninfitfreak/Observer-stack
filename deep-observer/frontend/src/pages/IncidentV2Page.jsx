import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { fetchIncidentV2 } from "../api_v2";
import V2IncidentPanel from "../components/V2IncidentPanel";

export default function IncidentV2Page() {
  const { incidentId } = useParams();
  const [incident, setIncident] = useState(null);
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState("");
  const reqSeqRef = useRef(0);

  useEffect(() => {
    const reqId = ++reqSeqRef.current;
    setStatus("loading");
    setError("");
    setIncident(null);
    fetchIncidentV2(incidentId)
      .then((payload) => {
        if (reqId !== reqSeqRef.current) return;
        setIncident(payload && typeof payload === "object" ? payload : null);
        setStatus("ready");
      })
      .catch((err) => {
        if (reqId !== reqSeqRef.current) return;
        setStatus("error");
        setError(err?.message || "Unable to load incident.");
      });
  }, [incidentId]);

  const scope = useMemo(() => {
    if (!incident) return {};
    const src = incident.scope && typeof incident.scope === "object" ? incident.scope : {};
    return {
      cluster: src.cluster || incident.cluster || "",
      namespace: src.namespace || incident.namespace || "",
      service: src.service || incident.service || "",
      start: src.incident_window_start || incident.telemetry_snapshot?.incident_window_start || incident.timestamp,
      end: src.incident_window_end || incident.telemetry_snapshot?.incident_window_end || incident.timestamp,
    };
  }, [incident]);

  return (
    <main className="mx-auto min-h-screen w-full max-w-[1500px] space-y-6 px-6 py-8">
      <Link className="text-sm text-cyan-300 hover:text-cyan-200" to="/v2">
        Back to V2 dashboard
      </Link>
      {status === "error" ? <div className="rounded-2xl border border-rose-400/30 bg-rose-500/10 p-4 text-rose-200">{error}</div> : null}
      <V2IncidentPanel incidentId={incidentId} scope={scope} emptyHint={status === "loading" ? "Loading incident..." : "No incident data."} />
    </main>
  );
}

