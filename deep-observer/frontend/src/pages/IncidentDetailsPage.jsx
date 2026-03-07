import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  fetchChanges,
  fetchClusterReport,
  fetchIncident,
  fetchObservabilityReport,
  fetchRunbooks,
  fetchServiceHealth,
  fetchSLOStatus,
  fetchTopology,
} from "../api";
import IncidentDetailsPanel from "../components/IncidentDetailsPanel";

export default function IncidentDetailsPage() {
  const { incidentId } = useParams();
  const [incident, setIncident] = useState(null);
  const [topology, setTopology] = useState({ nodes: [], edges: [] });
  const [serviceHealth, setServiceHealth] = useState([]);
  const [clusterReport, setClusterReport] = useState(null);
  const [changes, setChanges] = useState([]);
  const [sloStatus, setSloStatus] = useState([]);
  const [runbooks, setRunbooks] = useState([]);
  const [observabilityReport, setObservabilityReport] = useState(null);

  useEffect(() => {
    let cancelled = false;
    fetchIncident(incidentId)
      .then((payload) => {
        if (!payload || typeof payload !== "object") {
          setIncident(null);
          setTopology({ nodes: [], edges: [] });
          return null;
        }
        if (cancelled) return null;
        setIncident(payload);
        const end = new Date(payload.timestamp).toISOString();
        const start = new Date(new Date(payload.timestamp).getTime() - 60 * 60 * 1000).toISOString();
        const baseFilters = {
          cluster: payload.cluster,
          namespace: payload.namespace,
          service: payload.service,
          start,
          end,
        };
        return Promise.all([
          fetchTopology(baseFilters),
          fetchServiceHealth(baseFilters),
          fetchClusterReport(baseFilters),
          fetchChanges(baseFilters),
          fetchSLOStatus(baseFilters),
          fetchRunbooks({}),
          fetchObservabilityReport(baseFilters),
        ]);
      })
      .then((result) => {
        if (cancelled || !Array.isArray(result)) return;
        const [topologyPayload, serviceHealthPayload, clusterReportPayload, changesPayload, sloPayload, runbooksPayload, observabilityPayload] = result;
        setTopology({
          ...topologyPayload,
          nodes: Array.isArray(topologyPayload.nodes) ? topologyPayload.nodes : [],
          edges: Array.isArray(topologyPayload.edges) ? topologyPayload.edges : [],
        });
        setServiceHealth(Array.isArray(serviceHealthPayload) ? serviceHealthPayload : []);
        setClusterReport(clusterReportPayload && typeof clusterReportPayload === "object" ? clusterReportPayload : null);
        setChanges(Array.isArray(changesPayload) ? changesPayload : []);
        setSloStatus(Array.isArray(sloPayload) ? sloPayload : []);
        setRunbooks(Array.isArray(runbooksPayload) ? runbooksPayload : []);
        setObservabilityReport(observabilityPayload && typeof observabilityPayload === "object" ? observabilityPayload : null);
      })
      .catch(console.error);
    return () => {
      cancelled = true;
    };
  }, [incidentId]);

  return (
    <main className="mx-auto min-h-screen w-full max-w-[1400px] space-y-6 px-6 py-8">
      <Link className="text-sm text-cyan-300 hover:text-cyan-200" to="/">
        Back to dashboard
      </Link>
      <IncidentDetailsPanel
        incident={incident}
        topology={topology}
        serviceHealth={serviceHealth.find((item) => item.service_name === incident?.service)}
        clusterReport={clusterReport}
        changes={changes}
        sloStatus={sloStatus.filter((item) => item.service_name === incident?.service)}
        runbooks={runbooks}
        observabilityReport={observabilityReport}
      />
    </main>
  );
}
