import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { fetchDashboardV2 } from "../api_v2";
import { buildRange } from "../timeRange";
import V2IncidentPanel from "../components/V2IncidentPanel";

export default function DashboardV2Page() {
  const location = useLocation();
  const [filters, setFilters] = useState({ cluster: "", namespace: "", service: "" });
  const [timeRange, setTimeRange] = useState("24h");
  const [customRange, setCustomRange] = useState({ start: "", end: "" });
  const [appliedTimeRange, setAppliedTimeRange] = useState("24h");
  const [appliedCustomRange, setAppliedCustomRange] = useState({ start: "", end: "" });
  const [dashboard, setDashboard] = useState(null);
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState("");
  const [selectedIncidentId, setSelectedIncidentId] = useState("");
  const reqSeqRef = useRef(0);

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const cluster = params.get("cluster") || "";
    const namespace = params.get("namespace") || "";
    const service = params.get("service") || "";
    const start = params.get("start") || "";
    const end = params.get("end") || "";
    if (cluster || namespace || service) {
      setFilters({ cluster, namespace, service });
    }
    if (start && end) {
      setTimeRange("custom");
      setAppliedTimeRange("custom");
      setCustomRange({ start, end });
      setAppliedCustomRange({ start, end });
    }
  }, [location.search]);

  const range = useMemo(
    () => buildRange(appliedTimeRange, appliedCustomRange.start, appliedCustomRange.end),
    [appliedTimeRange, appliedCustomRange],
  );
  const query = useMemo(
    () => ({ ...filters, start: range.start, end: range.end, time_range: appliedTimeRange }),
    [filters, range, appliedTimeRange],
  );

  useEffect(() => {
    const requestId = ++reqSeqRef.current;
    setStatus("loading");
    setError("");
    setDashboard(null);
    setSelectedIncidentId("");
    console.debug("DashboardV2Page: dashboard fetch started", { requestId, query });
    fetchDashboardV2(query)
      .then((payload) => {
        if (requestId !== reqSeqRef.current) return;
        setDashboard(payload);
        setStatus("ready");
        const incidents = Array.isArray(payload?.incident_list) ? payload.incident_list : [];
        setSelectedIncidentId(incidents[0]?.incident_id || "");
        console.debug("DashboardV2Page: dashboard fetch completed", {
          requestId,
          incidents: incidents.length,
          topologyNodes: payload?.scoped_topology?.nodes?.length || 0,
          topologyEdges: payload?.scoped_topology?.edges?.length || 0,
        });
      })
      .catch((err) => {
        if (requestId !== reqSeqRef.current) return;
        setStatus("error");
        setError(err?.message || "Unable to load dashboard.");
        console.debug("DashboardV2Page: dashboard fetch failed", {
          requestId,
          error: err?.message || "unknown_error",
        });
      });
  }, [query]);

  const options = dashboard?.filter_options || { clusters: [], namespaces: [], services: [] };
  const incidents = Array.isArray(dashboard?.incident_list) ? dashboard.incident_list : [];
  const topology = dashboard?.scoped_topology || { available: false, nodes: [], edges: [] };

  const onPresetChange = (value) => {
    setTimeRange(value);
    if (value !== "custom") {
      setAppliedTimeRange(value);
      setAppliedCustomRange({ start: "", end: "" });
    }
  };

  const customValid =
    timeRange === "custom" &&
    customRange.start &&
    customRange.end &&
    new Date(customRange.start).toString() !== "Invalid Date" &&
    new Date(customRange.end).toString() !== "Invalid Date" &&
    new Date(customRange.start) <= new Date(customRange.end);

  const applyCustom = () => {
    if (!customValid) return;
    setAppliedTimeRange("custom");
    setAppliedCustomRange({ ...customRange });
  };

  return (
    <main className="mx-auto min-h-screen w-full max-w-[1600px] space-y-6 px-6 py-8">
      <header className="rounded-3xl border border-white/10 bg-slate-900/70 p-6">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-cyan-300">Deep Observer V2</p>
            <h1 className="mt-2 text-4xl font-semibold text-white">API-First Incident Truth</h1>
            <p className="mt-2 text-sm text-slate-400">V2 is isolated from legacy reconstruction logic. Legacy UI is still available for comparison.</p>
          </div>
          <Link className="text-sm text-cyan-300 hover:text-cyan-200" to="/legacy">
            Open Legacy
          </Link>
        </div>
      </header>

      <section className="rounded-3xl border border-white/10 bg-slate-900/60 p-4 grid gap-3 lg:grid-cols-5">
        <FilterSelect label="Cluster" value={filters.cluster} options={options.clusters} onChange={(value) => setFilters((prev) => ({ ...prev, cluster: value }))} />
        <FilterSelect label="Namespace" value={filters.namespace} options={options.namespaces} onChange={(value) => setFilters((prev) => ({ ...prev, namespace: value }))} />
        <FilterSelect label="Service" value={filters.service} options={options.services} onChange={(value) => setFilters((prev) => ({ ...prev, service: value }))} />
        <FilterSelect
          label="Time Range"
          value={timeRange}
          options={["15m", "1h", "4h", "24h", "7d", "custom"]}
          onChange={onPresetChange}
          includeAll={false}
        />
        {timeRange === "custom" ? (
          <div className="space-y-2">
            <input type="datetime-local" value={customRange.start} onChange={(event) => setCustomRange((prev) => ({ ...prev, start: event.target.value }))} className="w-full rounded-xl border border-white/10 bg-slate-950 px-3 py-2 text-sm text-white" />
            <input type="datetime-local" value={customRange.end} onChange={(event) => setCustomRange((prev) => ({ ...prev, end: event.target.value }))} className="w-full rounded-xl border border-white/10 bg-slate-950 px-3 py-2 text-sm text-white" />
            <button type="button" onClick={applyCustom} disabled={!customValid} className="rounded-full bg-cyan-500/20 px-3 py-1 text-xs text-cyan-200 disabled:opacity-40">
              Apply
            </button>
          </div>
        ) : (
          <div className="rounded-2xl border border-white/10 bg-slate-950/60 p-3 text-xs text-slate-400">
            Scope: {filters.cluster || "All"} / {filters.namespace || "All"} / {filters.service || "All"}
            <br />
            Window: {range.label}
          </div>
        )}
      </section>

      {status === "loading" ? <SimpleCard text="Loading dashboard..." /> : null}
      {status === "error" ? <SimpleCard text={error} isError /> : null}
      {status === "ready" ? (
        <>
          <section className="rounded-3xl border border-white/10 bg-slate-900/60 p-4">
            <h2 className="text-sm uppercase tracking-[0.2em] text-slate-400">Topology</h2>
            <p className="mt-2 text-sm text-slate-200">Available: {String(Boolean(topology.available))} | Nodes: {Array.isArray(topology.nodes) ? topology.nodes.length : 0} | Edges: {Array.isArray(topology.edges) ? topology.edges.length : 0}</p>
          </section>

          <section className="rounded-3xl border border-white/10 bg-slate-900/60 p-4">
            <h2 className="text-sm uppercase tracking-[0.2em] text-slate-400">Incidents</h2>
            {incidents.length ? (
              <div className="mt-3 space-y-2">
                {incidents.map((item) => (
                  <button
                    key={item.incident_id}
                    type="button"
                    onClick={() => setSelectedIncidentId(item.incident_id)}
                    className={`w-full rounded-2xl border px-4 py-3 text-left text-sm ${selectedIncidentId === item.incident_id ? "border-cyan-400/50 bg-cyan-500/10 text-cyan-100" : "border-white/10 bg-slate-950/40 text-slate-200"}`}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <span>{item.service} ({item.incident_type})</span>
                      <span className="text-xs text-slate-400">{new Date(item.timestamp).toLocaleString()}</span>
                    </div>
                  </button>
                ))}
              </div>
            ) : (
              <p className="mt-2 text-sm text-slate-400">{dashboard?.message || "No incidents."}</p>
            )}
          </section>

          <V2IncidentPanel
            incidentId={selectedIncidentId}
            scope={query}
            emptyHint={dashboard?.message || "No incidents for selected scope."}
          />
        </>
      ) : null}
    </main>
  );
}

function FilterSelect({ label, value, options, onChange, includeAll = true }) {
  const list = Array.isArray(options) ? options : [];
  return (
    <label className="space-y-1">
      <span className="text-[11px] uppercase tracking-[0.2em] text-slate-400">{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)} className="w-full rounded-xl border border-white/10 bg-slate-950 px-3 py-2 text-sm text-white">
        {includeAll ? <option value="">All</option> : null}
        {list.map((item) => (
          <option key={item} value={item}>
            {item}
          </option>
        ))}
      </select>
    </label>
  );
}

function SimpleCard({ text, isError }) {
  return (
    <div className={`rounded-2xl border p-4 text-sm ${isError ? "border-rose-400/30 bg-rose-500/10 text-rose-200" : "border-white/10 bg-slate-900/60 text-slate-300"}`}>
      {text}
    </div>
  );
}
