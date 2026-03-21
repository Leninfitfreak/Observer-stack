import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fetchDashboardScope } from "../api";
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
  const dashboardRequestSeqRef = useRef(0);

  const selectedIncident =
    (Array.isArray(incidents) ? incidents : []).find((incident) => incident.incident_id === selectedIncidentId) ||
    (Array.isArray(incidents) ? incidents[0] : null) ||
    null;

  const range = useMemo(
    () => buildRange(appliedTimeRange, appliedCustomRange.start, appliedCustomRange.end),
    [appliedTimeRange, appliedCustomRange],
  );
  const query = useMemo(
    () => ({ ...filters, start: range.start, end: range.end, time_range: appliedTimeRange }),
    [filters, range, appliedTimeRange],
  );

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
    let cancelled = false;
    setIncidentHint("Loading incidents for selected scope...");
    setSelectedIncidentId("");

    const load = async () => {
      const requestId = ++dashboardRequestSeqRef.current;
      console.debug("DashboardPage: dashboard scope fetch started", {
        requestId,
        query,
      });
      try {
        const payload = await fetchDashboardScope(query);
        if (cancelled || requestId !== dashboardRequestSeqRef.current) {
          console.debug("DashboardPage: dashboard scope fetch ignored (stale)", {
            requestId,
          });
          return;
        }

        const safeIncidents = Array.isArray(payload?.incident_list) ? payload.incident_list : [];
        const safeTopology =
          payload?.scoped_topology && typeof payload.scoped_topology === "object"
            ? {
                ...payload.scoped_topology,
                nodes: Array.isArray(payload.scoped_topology.nodes) ? payload.scoped_topology.nodes : [],
                edges: Array.isArray(payload.scoped_topology.edges) ? payload.scoped_topology.edges : [],
              }
            : { nodes: [], edges: [] };

        setIncidents(safeIncidents);
        setTopology(safeTopology);
        setOptions({
          clusters: Array.isArray(payload?.filter_options?.clusters) ? payload.filter_options.clusters : [],
          namespaces: Array.isArray(payload?.filter_options?.namespaces) ? payload.filter_options.namespaces : [],
          services: Array.isArray(payload?.filter_options?.services) ? payload.filter_options.services : [],
        });
        setIncidentHint(safeIncidents.length ? "" : payload?.no_results_state?.message || "No incidents match the current filters.");
        setSelectedIncidentId((current) => {
          if (!safeIncidents.length) return "";
          return safeIncidents.some((item) => item.incident_id === current) ? current : safeIncidents[0].incident_id;
        });
        console.debug("DashboardPage: dashboard scope fetch completed", {
          requestId,
          incidents: safeIncidents.length,
          selectedIncidentId: safeIncidents[0]?.incident_id || "",
          topologyNodes: safeTopology.nodes.length,
          topologyEdges: safeTopology.edges.length,
        });
      } catch (error) {
        console.error(error);
        if (!cancelled && requestId === dashboardRequestSeqRef.current) {
          setIncidents([]);
          setTopology({ nodes: [], edges: [] });
          setIncidentHint("Unable to load dashboard scope.");
          console.debug("DashboardPage: dashboard scope fetch failed", {
            requestId,
            error: error?.message || "unknown_error",
          });
        }
      }
    };

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

  useEffect(() => {
    console.debug("DashboardPage: filters updated", {
      filters,
      appliedTimeRange,
      range,
      selectedIncidentId,
    });
  }, [filters, appliedTimeRange, range, selectedIncidentId]);

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
