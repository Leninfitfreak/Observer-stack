import { useEffect, useRef, useState } from "react";
import { fetchIncidentViewV2, fetchReasoningHistoryV2, retryReasoningV2, runReasoningV2 } from "../api_v2";

const MAX_POLL_ATTEMPTS = 40;

export default function V2IncidentPanel({ incidentId, scope, emptyHint }) {
  const [view, setView] = useState(null);
  const [status, setStatus] = useState("idle");
  const [error, setError] = useState("");
  const [history, setHistory] = useState([]);
  const [reasoningBusy, setReasoningBusy] = useState(false);
  const viewReqSeqRef = useRef(0);
  const historyReqSeqRef = useRef(0);

  const loadView = async () => {
    if (!incidentId) {
      setView(null);
      setHistory([]);
      setStatus("empty");
      setError("");
      return null;
    }
    const reqId = ++viewReqSeqRef.current;
    setStatus("loading");
    setError("");
    setView(null);
    console.debug("V2IncidentPanel: evidence fetch started", { reqId, incidentId, scope });
    try {
      const payload = await fetchIncidentViewV2(incidentId, scope);
      if (reqId !== viewReqSeqRef.current) return null;
      setView(payload);
      setStatus("ready");
      console.debug("V2IncidentPanel: evidence fetch completed", {
        reqId,
        incidentId,
        state: payload?.state,
        sparse: payload?.sparse,
      });
      return payload;
    } catch (err) {
      if (reqId !== viewReqSeqRef.current) return null;
      setError(err?.message || "Unable to load incident details.");
      setStatus("error");
      console.debug("V2IncidentPanel: evidence fetch failed", { reqId, incidentId, error: err?.message || "unknown_error" });
      return null;
    }
  };

  useEffect(() => {
    loadView().catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [incidentId, scope.cluster, scope.namespace, scope.service, scope.start, scope.end]);

  useEffect(() => {
    if (!incidentId) return;
    const reqId = ++historyReqSeqRef.current;
    fetchReasoningHistoryV2(incidentId)
      .then((payload) => {
        if (reqId !== historyReqSeqRef.current) return;
        setHistory(Array.isArray(payload) ? payload : []);
      })
      .catch(() => {});
  }, [incidentId]);

  const pollReasoning = async (attempt = 0) => {
    if (attempt > MAX_POLL_ATTEMPTS) return;
    const payload = await loadView();
    const mode = payload?.reasoning?.status;
    if (mode === "completed" || mode === "completed_with_fallback" || mode === "failed") {
      return;
    }
    setTimeout(() => {
      pollReasoning(attempt + 1).catch(() => {});
    }, 3000);
  };

  const triggerReasoning = async () => {
    if (!incidentId || reasoningBusy) return;
    setReasoningBusy(true);
    try {
      const reasoningStatus = (view?.reasoning?.status || "not_generated").toLowerCase();
      if (reasoningStatus === "not_generated") {
        await runReasoningV2(incidentId);
      } else {
        await retryReasoningV2(incidentId);
      }
      await pollReasoning(0);
    } catch (err) {
      setError(err?.message || "Unable to run reasoning.");
      setStatus("error");
    } finally {
      setReasoningBusy(false);
    }
  };

  if (!incidentId) {
    return <EmptyCard text={emptyHint || "Select an incident to view V2 details."} />;
  }
  if (status === "loading") {
    return <EmptyCard text="Loading selected incident..." subtle />;
  }
  if (status === "error") {
    return <EmptyCard text={error || "Failed to load selected incident."} isError />;
  }
  if (!view) {
    return <EmptyCard text="No selected incident data available." />;
  }

  const isSparse = Boolean(view.sparse) || view.state === "predictive_sparse";
  const reasoning = view.reasoning || {};
  const renderMode = isSparse ? "sparse" : "full";
  console.debug("V2IncidentPanel: render mode selected", {
    incidentId,
    renderMode,
    state: view.state,
    reasoningStatus: reasoning.status || "not_generated",
  });

  return (
    <div className="rounded-3xl border border-white/10 bg-slate-900/70 p-6 space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-[0.28em] text-cyan-300">Deep Observer V2</p>
          <h2 className="mt-2 text-2xl font-semibold text-white">{view.incident?.service || "Unknown service"}</h2>
          <p className="mt-1 text-sm text-slate-400">
            {view.normalized_scope?.cluster || "Unknown cluster"} / {view.normalized_scope?.namespace || "Unknown namespace"} / {new Date(view.incident?.timestamp).toLocaleString()}
          </p>
        </div>
        <div className="rounded-2xl border border-white/10 bg-slate-950/80 px-4 py-2 text-right">
          <div className="text-[11px] uppercase tracking-[0.2em] text-slate-400">State</div>
          <div className="text-sm font-semibold text-white">{view.state}</div>
        </div>
      </div>

      {isSparse ? (
        <SparseSection sparse={view.sparse_predictive} />
      ) : (
        <FullSection view={view} />
      )}

      <div className="rounded-2xl border border-white/10 bg-slate-950/60 p-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm uppercase tracking-[0.2em] text-slate-300">Reasoning</h3>
          <button
            type="button"
            disabled={reasoningBusy || !reasoning.allowed}
            onClick={triggerReasoning}
            className="rounded-full bg-cyan-500/20 px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] text-cyan-200 disabled:opacity-50"
          >
            {reasoningBusy ? "Running..." : "Run Reasoning"}
          </button>
        </div>
        <p className="mt-2 text-sm text-slate-200">Status: {reasoning.status || "not_generated"}</p>
        <p className="mt-1 text-sm text-slate-300">{reasoning.summary || "Reasoning unavailable."}</p>
        <p className="mt-1 text-xs text-slate-400">Mode: {reasoning.execution_mode || "pending"} | Confidence: {Number(reasoning.confidence || 0).toFixed(2)}</p>
        {reasoning.error ? <p className="mt-2 text-xs text-rose-300">{reasoning.error}</p> : null}
        {history.length ? <p className="mt-2 text-xs text-slate-500">Reasoning runs: {history.length}</p> : null}
      </div>
    </div>
  );
}

function SparseSection({ sparse }) {
  const direct = sparse?.direct_evidence || {};
  const contextual = sparse?.contextual_evidence || {};
  const nearest = Array.isArray(sparse?.nearest_observed) ? sparse.nearest_observed : [];
  const nextSteps = Array.isArray(sparse?.next_steps) ? sparse.next_steps : [];

  return (
    <div className="rounded-2xl border border-amber-500/30 bg-amber-500/5 p-4 space-y-3">
      <p className="text-sm font-semibold text-amber-200">{sparse?.summary || "Insufficient incident-scoped telemetry for RCA."}</p>
      <div className="grid gap-3 md:grid-cols-2 text-sm text-slate-200">
        <div>Requests: {direct.request_count ?? 0}</div>
        <div>Logs: {direct.log_count ?? 0}</div>
        <div>Traces: {direct.trace_sample_count ?? 0}</div>
        <div>Metrics: {Object.keys(direct.metric_highlights || {}).length}</div>
      </div>
      <p className="text-xs text-slate-400">Contextual: topology={contextual.topology || "missing"}, database={contextual.database || "missing"}, messaging={contextual.messaging || "missing"}</p>
      {nextSteps.length ? (
        <ul className="text-sm text-slate-200 space-y-1">
          {nextSteps.map((step) => <li key={step}>- {step}</li>)}
        </ul>
      ) : null}
      {nearest.length ? (
        <div className="text-sm text-slate-200">
          <p className="text-xs uppercase tracking-[0.2em] text-slate-400 mb-1">Nearest observed incidents</p>
          {nearest.map((item) => (
            <p key={item.incident_id}>- {item.service} at {new Date(item.timestamp).toLocaleString()}</p>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function FullSection({ view }) {
  const direct = view.direct_evidence || {};
  const contextual = view.contextual_evidence || {};
  const topology = view.incident_topology || { nodes: [], edges: [] };
  const signals = Array.isArray(view.signals) ? view.signals : [];
  const impacted = Array.isArray(view.impacted_services) ? view.impacted_services : [];
  const propagation = Array.isArray(view.propagation_path) ? view.propagation_path : [];
  const related = Array.isArray(view.related_incidents) ? view.related_incidents : [];
  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-3">
        <Info title="Requests" value={direct.request_count ?? 0} />
        <Info title="Logs" value={direct.log_count ?? 0} />
        <Info title="Traces" value={direct.trace_sample_count ?? 0} />
        <Info title="P95 Latency" value={`${Number(direct.p95_latency_ms || 0).toFixed(2)} ms`} />
        <Info title="Error Rate" value={Number(direct.error_rate || 0).toFixed(4)} />
        <Info title="Observability" value={`${Number(view.observability_score || 0).toFixed(0)}%`} />
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <Card title="Signals" values={signals} empty="No signals detected." />
        <Card title="Missing Evidence" values={view.missing_evidence || []} empty="No missing evidence." />
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <Card title="Impacted Services" values={impacted} empty="No impacted services." />
        <Card title="Propagation Path" values={propagation} empty="No propagation path." />
      </div>
      <div className="rounded-2xl border border-white/10 bg-slate-950/60 p-4">
        <p className="text-xs uppercase tracking-[0.2em] text-slate-400">Topology</p>
        <p className="mt-1 text-sm text-slate-200">Nodes: {Array.isArray(topology.nodes) ? topology.nodes.length : 0} | Edges: {Array.isArray(topology.edges) ? topology.edges.length : 0}</p>
        <p className="mt-1 text-xs text-slate-400">Contextual: topology={contextual.topology || "missing"}, database={contextual.database || "missing"}, messaging={contextual.messaging || "missing"}</p>
      </div>
      <div className="rounded-2xl border border-white/10 bg-slate-950/60 p-4">
        <p className="text-xs uppercase tracking-[0.2em] text-slate-400">Related Incidents</p>
        {related.length ? related.map((item) => (
          <p key={item.incident_id} className="mt-1 text-sm text-slate-200">- {item.service} ({item.incident_type}) at {new Date(item.timestamp).toLocaleString()}</p>
        )) : <p className="mt-1 text-sm text-slate-400">No related incidents.</p>}
      </div>
    </div>
  );
}

function Info({ title, value }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-slate-950/60 p-3">
      <p className="text-[11px] uppercase tracking-[0.2em] text-slate-400">{title}</p>
      <p className="mt-1 text-sm font-semibold text-white">{value}</p>
    </div>
  );
}

function Card({ title, values, empty }) {
  const list = Array.isArray(values) ? values : [];
  return (
    <div className="rounded-2xl border border-white/10 bg-slate-950/60 p-4">
      <p className="text-xs uppercase tracking-[0.2em] text-slate-400">{title}</p>
      {list.length ? list.map((item) => <p key={`${title}-${item}`} className="mt-1 text-sm text-slate-200">- {item}</p>) : <p className="mt-1 text-sm text-slate-400">{empty}</p>}
    </div>
  );
}

function EmptyCard({ text, isError, subtle }) {
  return (
    <div className={`rounded-3xl border p-6 text-sm ${isError ? "border-rose-400/30 bg-rose-500/10 text-rose-200" : subtle ? "border-white/10 bg-slate-900/60 text-slate-400" : "border-white/10 bg-slate-900/60 text-slate-300"}`}>
      {text}
    </div>
  );
}
