import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  fetchChanges,
  fetchClusterReport,
  fetchFilters,
  fetchIncidents,
  fetchObservabilityReport,
  fetchRunbooks,
  fetchServiceHealth,
  fetchSLOStatus,
  fetchTopology,
} from "../api";
import FilterBar from "../components/FilterBar";
import Header from "../components/Header";
import IncidentDetailsPanel from "../components/IncidentDetailsPanel";
import IncidentTable from "../components/IncidentTable";
import ServiceTopologyGraph from "../components/ServiceTopologyGraph";
import { buildRange } from "../timeRange";

export default function DashboardPage() {
  const navigate = useNavigate();
  const detailsPanelRef = useRef(null);
  const shouldScrollToDetailsRef = useRef(false);
  const [filters, setFilters] = useState({ cluster: "", namespace: "", service: "" });
  const [options, setOptions] = useState({ clusters: [], namespaces: [], services: [] });
  const [incidents, setIncidents] = useState([]);
  const [topology, setTopology] = useState({ nodes: [], edges: [] });
  const [selectedIncidentId, setSelectedIncidentId] = useState("");
  const [timeRange, setTimeRange] = useState("24h");
  const [customRange, setCustomRange] = useState({ start: "", end: "" });
  const [appliedTimeRange, setAppliedTimeRange] = useState("24h");
  const [appliedCustomRange, setAppliedCustomRange] = useState({ start: "", end: "" });
  const [liveMode, setLiveMode] = useState(false);
  const [incidentHint, setIncidentHint] = useState("");
  const [serviceHealth, setServiceHealth] = useState([]);
  const [clusterReport, setClusterReport] = useState(null);
  const [changes, setChanges] = useState([]);
  const [sloStatus, setSloStatus] = useState([]);
  const [runbooks, setRunbooks] = useState([]);
  const [observabilityReport, setObservabilityReport] = useState(null);

  const range = useMemo(
    () => buildRange(appliedTimeRange, appliedCustomRange.start, appliedCustomRange.end),
    [appliedTimeRange, appliedCustomRange],
  );
  const query = useMemo(
    () => ({ ...filters, start: range.start, end: range.end, time_range: appliedTimeRange }),
    [filters, range, appliedTimeRange],
  );
  const selectedIncident =
    (Array.isArray(incidents) ? incidents : []).find((incident) => incident.incident_id === selectedIncidentId) ||
    (Array.isArray(incidents) ? incidents[0] : null) ||
    null;

  useEffect(() => {
    if (!selectedIncidentId || !shouldScrollToDetailsRef.current || !detailsPanelRef.current) return;
    detailsPanelRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
    shouldScrollToDetailsRef.current = false;
  }, [selectedIncidentId]);

  const handleIncidentSelect = (incidentId, options = {}) => {
    if (options.scroll) {
      shouldScrollToDetailsRef.current = true;
    }
    setSelectedIncidentId(incidentId);
  };

  const handlePresetChange = (value) => {
    setTimeRange(value);
    if (value !== "custom") {
      setAppliedTimeRange(value);
      setAppliedCustomRange({ start: "", end: "" });
    }
  };

  const customStart = customRange.start;
  const customEnd = customRange.end;
  const customValid =
    timeRange === "custom" &&
    customStart &&
    customEnd &&
    new Date(customStart).toString() !== "Invalid Date" &&
    new Date(customEnd).toString() !== "Invalid Date" &&
    new Date(customStart) <= new Date(customEnd);

  const handleApplyCustom = () => {
    if (!customValid) return;
    setAppliedTimeRange("custom");
    setAppliedCustomRange({ start: customStart, end: customEnd });
  };

  const handleClearCustom = () => {
    setCustomRange({ start: "", end: "" });
  };

  useEffect(() => {
    fetchFilters()
      .then((payload) =>
        setOptions({
          clusters: Array.isArray(payload?.clusters) ? payload.clusters : [],
          namespaces: Array.isArray(payload?.namespaces) ? payload.namespaces : [],
          services: Array.isArray(payload?.services) ? payload.services : [],
        }),
      )
      .catch(console.error);
  }, []);

  useEffect(() => {
    let cancelled = false;

    const load = () =>
      Promise.all([
        fetchIncidents(query),
        fetchTopology(query),
        fetchServiceHealth(query),
        fetchClusterReport(query),
        fetchChanges(query),
        fetchSLOStatus(query),
        fetchRunbooks({}),
        fetchObservabilityReport(query),
      ]).then(([incidentData, topologyData, healthData, reportData, changesData, sloData, runbookData, observabilityData]) => {
          if (cancelled) return;
          const safeIncidents = Array.isArray(incidentData) ? incidentData : [];
          const safeTopology =
            topologyData && typeof topologyData === "object"
              ? {
                  ...topologyData,
                  nodes: Array.isArray(topologyData.nodes) ? topologyData.nodes : [],
                  edges: Array.isArray(topologyData.edges) ? topologyData.edges : [],
                }
              : { nodes: [], edges: [] };
          setIncidents(safeIncidents);
          setIncidentHint(safeIncidents.length ? "" : "No incidents match the current filters.");
          setTopology(safeTopology);
          setServiceHealth(Array.isArray(healthData) ? healthData : []);
          setClusterReport(reportData && typeof reportData === "object" ? reportData : null);
          setChanges(Array.isArray(changesData) ? changesData : []);
          setSloStatus(Array.isArray(sloData) ? sloData : []);
          setRunbooks(Array.isArray(runbookData) ? runbookData : []);
          setObservabilityReport(observabilityData && typeof observabilityData === "object" ? observabilityData : null);
          setSelectedIncidentId((current) => {
            if (!safeIncidents.length) return "";
            return safeIncidents.some((item) => item.incident_id === current) ? current : safeIncidents[0].incident_id;
          });
          console.info("[filters] query=", query);
          console.info("[filters] incidents_count=", safeIncidents.length);
          console.info("[filters] selected_incident=", safeIncidents[0]?.incident_id || "");
        }).catch(console.error);

    load();
    if (!liveMode) {
      return () => {
        cancelled = true;
      };
    }

    const timer = setInterval(load, 10000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [query, liveMode]);

  return (
    <main className="mx-auto min-h-screen w-full max-w-[1600px] space-y-6 px-6 py-8">
      <Header liveMode={liveMode} onToggleLive={() => setLiveMode((current) => !current)} rangeLabel={range.label} />
      <FilterBar
        filters={filters}
        options={options}
        timeRange={timeRange}
        customRange={customRange}
        onFilterChange={(key, value) => setFilters((current) => ({ ...current, [key]: value }))}
        onTimeRangeChange={handlePresetChange}
        onCustomRangeChange={(key, value) => setCustomRange((current) => ({ ...current, [key]: value }))}
        onApplyCustom={handleApplyCustom}
        customRangeValid={customValid}
        onClearCustom={handleClearCustom}
        scopeLabel={`${filters.cluster || "All clusters"} · ${filters.namespace || "All namespaces"} · ${filters.service || "All services"} · ${
          range.label
        }`}
      />
      <ServiceTopologyGraph topology={topology} selectedService={filters.service || selectedIncident?.service} />
      <section ref={detailsPanelRef}>
        <IncidentDetailsPanel
          incident={selectedIncident}
          filterQuery={query}
          emptyHint={incidentHint || "No incidents found for the selected filters."}
          serviceHealth={serviceHealth.find((item) => item.service_name === (selectedIncident?.service || filters.service))}
          clusterReport={clusterReport}
          changes={changes}
          sloStatus={sloStatus.filter((item) => item.service_name === (selectedIncident?.service || filters.service))}
          runbooks={runbooks}
          observabilityReport={observabilityReport}
        />
      </section>
      <IncidentTable
        incidents={incidents}
        selectedIncidentId={selectedIncident?.incident_id}
        onSelectIncident={handleIncidentSelect}
        onOpenIncident={(incidentId) => navigate(`/incidents/${incidentId}`)}
        emptyHint={incidentHint}
      />
    </main>
  );
}
