import { useEffect, useMemo, useState } from "react";
import {
  fetchIncident,
  fetchTimeline,
  runReasoning,
  retryReasoning,
  fetchReasoningHistory,
  fetchReasoningRun,
  fetchCorrelations,
  fetchIncidents,
  updateIncidentWorkflow,
} from "../api";
import IncidentTable from "./IncidentTable";

export default function IncidentDetailsPanel({
  incident,
  filterQuery,
  emptyHint,
  serviceHealth,
  clusterReport,
  changes,
  sloStatus,
  runbooks,
  observabilityReport,
}) {
  const [timeline, setTimeline] = useState([]);
  const [activeIncident, setActiveIncident] = useState(null);
  const [reasoningStatus, setReasoningStatus] = useState("");
  const [reasoningError, setReasoningError] = useState("");
  const [reasoningBusy, setReasoningBusy] = useState(false);
  const [reasoningHistory, setReasoningHistory] = useState([]);
  const [selectedRun, setSelectedRun] = useState(null);
  const [correlations, setCorrelations] = useState([]);
  const [workflowUpdating, setWorkflowUpdating] = useState(false);
  const [incidentCluster, setIncidentCluster] = useState(null);
  const [incidentHistory, setIncidentHistory] = useState([]);
  const [incidentList, setIncidentList] = useState([]);

  useEffect(() => {
    if (!incident) return;
    fetchTimeline(incident.incident_id)
      .then((payload) => {
        const events = Array.isArray(payload.events) ? payload.events : [];
        setTimeline(filterTimelineEvents(events, filterQuery));
      })
      .catch(console.error);
  }, [incident, filterQuery]);

  useEffect(() => {
    if (!incident) {
      setActiveIncident(null);
      setReasoningStatus("");
      setReasoningError("");
      setReasoningBusy(false);
      setReasoningHistory([]);
      setSelectedRun(null);
      setCorrelations([]);
      return;
    }
    setActiveIncident(incident);
    setReasoningStatus(incident.reasoning_status || "");
    setReasoningError(incident.reasoning_error || "");
    setReasoningBusy(false);
  }, [incident]);

  useEffect(() => {
    if (!incident) return;
    fetchReasoningHistory(incident.incident_id)
      .then((payload) => {
        const items = Array.isArray(payload) ? payload : [];
        setReasoningHistory(items);
        setSelectedRun(items[0] || null);
      })
      .catch(console.error);
    fetchCorrelations(incident.incident_id)
      .then((payload) => setCorrelations(Array.isArray(payload) ? payload : []))
      .catch(console.error);
    fetchIncidents(filterQuery)
      .then((payload) => {
        const items = Array.isArray(payload) ? payload : [];
        setIncidentCluster(buildIncidentCluster(incident, items));
        setIncidentHistory(buildIncidentHistory(incident, items));
        setIncidentList(items);
      })
      .catch(console.error);
  }, [incident, filterQuery]);

  const chartPoints = useMemo(
    () =>
      timeline
        .filter((event) => Number.isFinite(Number(event?.value)))
        .slice(-8)
        .map((event) => ({
          ...event,
          ts: new Date(event.timestamp).toLocaleTimeString(),
          value: Number(event.value),
        })),
    [timeline],
  );

  const currentIncident = activeIncident || incident;
  if (!currentIncident) {
    return (
      <section className="rounded-3xl border border-white/10 bg-slate-900/60 p-6 text-sm text-slate-400">
        {emptyHint || "No incidents found for the selected filters."}
      </section>
    );
  }

  const reasoning = currentIncident.reasoning;
  const coverage = reasoning?.observability_summary || {};
  const anomalyScore = formatScore(currentIncident.anomaly_score);
  const telemetryEvidence = buildTelemetryEvidence(currentIncident);
  const impactedServices = formatImpactedServices(currentIncident.impacts);
  const derivedStatus = reasoningStatus || currentIncident.reasoning_status || (reasoning ? "completed" : "not_generated");
  const canRunReasoning = ["not_generated", "failed", "completed"].includes(derivedStatus) && !reasoningBusy;
  const confidenceDetails = reasoning?.confidence_explanation || {};
  const runDetail = selectedRun && selectedRun.reasoning_run_id ? selectedRun : null;
  const prioritizedActions = buildPrioritizedActions(currentIncident, reasoning);
  const decisionPanel = buildDecisionPanel(currentIncident, reasoning, prioritizedActions);
  const signalSummary = buildSignalSummary(currentIncident, reasoning);
  const logSummary = buildLogSummary(currentIncident);
  const impactSummary = buildImpactSummary(currentIncident, reasoning);
  const incidentTimeline = buildIncidentTimeline(currentIncident, reasoning);
  const observabilityGaps = buildObservabilityGaps(currentIncident, reasoning);
  const trustScore = buildTrustScore(currentIncident, reasoning, signalSummary, observabilityGaps);
  const workflowStatus = (currentIncident.workflow_status || "open").toLowerCase();

  const refreshIncident = async () => {
    const updated = await fetchIncident(currentIncident.incident_id);
    if (updated) {
      setActiveIncident(updated);
      setReasoningStatus(updated.reasoning_status || derivedStatus);
      setReasoningError(updated.reasoning_error || "");
      fetchReasoningHistory(updated.incident_id)
        .then((payload) => {
          const items = Array.isArray(payload) ? payload : [];
          setReasoningHistory(items);
          setSelectedRun(items[0] || null);
        })
        .catch(console.error);
      fetchCorrelations(updated.incident_id)
        .then((payload) => setCorrelations(Array.isArray(payload) ? payload : []))
        .catch(console.error);
    }
    return updated;
  };

  const pollForReasoning = async (attempt = 0) => {
    if (attempt > 10) return;
    const updated = await refreshIncident();
    const status = updated?.reasoning_status || derivedStatus;
    if (status === "completed" || status === "failed") return;
    setTimeout(() => {
      pollForReasoning(attempt + 1).catch(() => {});
    }, 3000);
  };

  const handleOpenIncident = async (incidentId) => {
    if (!incidentId) return;
    try {
      const updated = await fetchIncident(incidentId);
      if (updated) {
        setActiveIncident(updated);
      }
    } catch (err) {
      console.error(err);
    }
  };

  const updateWorkflow = async (status) => {
    if (!currentIncident || workflowUpdating) return;
    setWorkflowUpdating(true);
    try {
      const updated = await updateIncidentWorkflow(currentIncident.incident_id, {
        status,
      });
      if (updated) {
        setActiveIncident(updated);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setWorkflowUpdating(false);
    }
  };

  const handleRunReasoning = async () => {
    if (!currentIncident) return;
    setReasoningBusy(true);
    setReasoningStatus("running");
    setReasoningError("");
    try {
      const response =
        derivedStatus === "not_generated"
          ? await runReasoning(currentIncident.incident_id)
          : await retryReasoning(currentIncident.incident_id);
      setReasoningStatus(response?.status || "pending");
      await pollForReasoning(0);
    } catch (err) {
      setReasoningStatus("failed");
      setReasoningError(err?.message || "Reasoning request failed");
    } finally {
      setReasoningBusy(false);
    }
  };

  const handleSelectRun = async (run) => {
    if (!run || !currentIncident) {
      setSelectedRun(null);
      return;
    }
    try {
      const detail = await fetchReasoningRun(currentIncident.incident_id, run.reasoning_run_id);
      setSelectedRun(detail || run);
    } catch {
      setSelectedRun(run);
    }
  };

  return (
    <section className="space-y-4">
      <div className="rounded-3xl border border-white/10 bg-slate-900/60 p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.3em] text-cyan-300">Incident Details Panel</p>
            <h2 className="mt-2 text-2xl font-semibold text-white">{currentIncident.service}</h2>
            <p className="mt-1 text-sm text-slate-400">
              {currentIncident.cluster} / {currentIncident.namespace} / {new Date(currentIncident.timestamp).toLocaleString()}
            </p>
          </div>
          <div className="rounded-3xl border border-white/10 bg-slate-950/80 px-4 py-3 text-right">
            <div className="text-xs uppercase tracking-[0.3em] text-slate-400">Anomaly Score</div>
            <div className="mt-1 text-2xl font-semibold text-white">{anomalyScore}</div>
          </div>
        </div>

        <div className="mt-6 grid gap-4 lg:grid-cols-2">
          <InfoCard title="Root Cause Service" value={reasoning?.root_cause_service || currentIncident.root_cause_entity || "Pending"} />
          <InfoCard title="Root Cause Signal" value={reasoning?.root_cause_signal || toList(currentIncident.signals).join(", ")} />
          <InfoCard title="Customer Impact" value={reasoning?.customer_impact || reasoning?.impact_assessment || "Pending"} />
          <InfoCard title="Observability Score" value={`${reasoning?.observability_score ?? coverage.observability_score ?? 0}%`} />
          <InfoCard title="Service Health Score" value={`${formatScore(serviceHealth?.health_score ?? 0)} / 100`} />
          <InfoCard
            title="Root Cause Confidence"
            value={formatConfidenceLabel(reasoning?.confidence_score ?? currentIncident.predictive_confidence ?? 0, "Confidence pending")}
          />
          <InfoCard title="Incident Type" value={currentIncident.incident_type || "observed"} />
        </div>

        <div className="mt-6 rounded-3xl border border-white/10 bg-slate-950/85 p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.3em] text-cyan-300">Decision Panel</p>
            <p className="mt-1 text-xs text-slate-500">Operator guidance at a glance</p>
            </div>
            <span className="rounded-full bg-cyan-500/20 px-3 py-1 text-xs font-semibold uppercase tracking-[0.3em] text-cyan-200">
              Confidence {formatScore(decisionPanel.confidence_score)}
            </span>
          </div>
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <InfoCard title="What is broken?" value={decisionPanel.root_cause} />
            <InfoCard title="Why does it matter?" value={decisionPanel.impact_summary} />
          </div>
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <InfoCard title="Immediate Action" value={decisionPanel.immediate_action} />
            <div className="rounded-3xl border border-white/10 bg-slate-900/60 p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.3em] text-slate-500">Next Actions</p>
              <ul className="mt-2 space-y-2 text-sm text-slate-200">
                {decisionPanel.next_actions.length
                  ? decisionPanel.next_actions.map((item) => <li key={item}>- {toText(item)}</li>)
                  : <li className="text-slate-500">No next actions yet.</li>}
              </ul>
            </div>
          </div>
          <div className="mt-4 rounded-3xl border border-white/10 bg-slate-900/60 p-4">
            <p className="text-xs font-semibold uppercase tracking-[0.3em] text-slate-500">Investigation Steps</p>
            <ul className="mt-2 space-y-2 text-sm text-slate-200">
              {decisionPanel.investigation_steps.length
                ? decisionPanel.investigation_steps.map((item) => <li key={item}>- {toText(item)}</li>)
                : <li className="text-slate-500">No additional investigation steps.</li>}
            </ul>
          </div>
        </div>

        <div className="mt-6 rounded-3xl border border-white/10 bg-slate-950/70 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold uppercase tracking-[0.3em] text-slate-400">Incident Lifecycle</h3>
              <p className="mt-1 text-xs text-slate-500">Track the current lifecycle state.</p>
            </div>
            <span className="rounded-full bg-slate-800 px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] text-slate-200">
              {formatWorkflowStatus(workflowStatus)}
            </span>
          </div>
          <div className="mt-4 grid gap-2 lg:grid-cols-3">
            <button
              type="button"
              onClick={() => updateWorkflow("acknowledged")}
              disabled={workflowUpdating}
              className="rounded-full bg-cyan-500/20 px-3 py-2 text-xs font-semibold uppercase tracking-[0.2em] text-cyan-200 hover:bg-cyan-500/30"
            >
              Mark Acknowledged
            </button>
            <button
              type="button"
              onClick={() => updateWorkflow("investigating")}
              disabled={workflowUpdating}
              className="rounded-full bg-amber-500/20 px-3 py-2 text-xs font-semibold uppercase tracking-[0.2em] text-amber-200 hover:bg-amber-500/30"
            >
              Mark Investigating
            </button>
            <button
              type="button"
              onClick={() => updateWorkflow("resolved")}
              disabled={workflowUpdating}
              className="rounded-full bg-emerald-500/20 px-3 py-2 text-xs font-semibold uppercase tracking-[0.2em] text-emerald-200 hover:bg-emerald-500/30"
            >
              Mark Resolved
            </button>
          </div>
          <div className="mt-3 text-xs text-slate-500">
            Acknowledged: {formatTimestamp(currentIncident.acknowledged_at)} ·
            Investigating: {formatTimestamp(currentIncident.investigating_at)} ·
            Resolved: {formatTimestamp(currentIncident.resolved_at)} ·
            Last updated: {formatTimestamp(currentIncident.workflow_updated_at)}
          </div>
        </div>

        <div className="mt-6 grid gap-6 xl:grid-cols-2">
          <div className="rounded-3xl border border-white/10 bg-slate-950/70 p-4">
            <h3 className="text-sm font-semibold uppercase tracking-[0.3em] text-slate-400">Action Prioritization</h3>
            <p className="mt-2 text-xs text-slate-500">Sorted by priority, then confidence.</p>
            <div className="mt-4 space-y-3">
              {prioritizedActions.length ? prioritizedActions.map((action, index) => (
                <div
                  key={`${action.label}-${index}`}
                  className={`rounded-2xl border border-white/10 px-4 py-3 ${
                    index === 0 ? "bg-cyan-500/10" : "bg-slate-900/60"
                  }`}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-sm font-semibold text-white">{toText(action.label)}</span>
                    <span className={`text-xs font-semibold uppercase tracking-[0.2em] ${priorityColor(action.priority)}`}>
                      {action.priority}
                    </span>
                  </div>
                  <div className="mt-2 text-xs text-slate-400">
                    Confidence {formatScore(action.confidence)} · Effort {action.estimated_effort} · Risk {action.risk_level}
                  </div>
                </div>
              )) : (
                <p className="text-slate-500">No prioritized actions available yet.</p>
              )}
            </div>
          </div>

          <div className="rounded-3xl border border-white/10 bg-slate-950/70 p-4">
            <h3 className="text-sm font-semibold uppercase tracking-[0.3em] text-slate-400">Signal Summary</h3>
            <div className="mt-4 grid gap-4">
              <SignalGroup title="Critical Signals" items={signalSummary.critical_signals} />
              <SignalGroup title="Secondary Signals" items={signalSummary.secondary_signals} />
              <SignalGroup title="Missing Signals" items={signalSummary.missing_signals} />
            </div>
          </div>
        </div>

        <div className="mt-6 grid gap-6 xl:grid-cols-2">
          <div className="rounded-3xl border border-white/10 bg-slate-950/70 p-4">
            <h3 className="text-sm font-semibold uppercase tracking-[0.3em] text-slate-400">Trust Score</h3>
            <div className="mt-3 space-y-2 text-sm text-slate-200">
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-500">Score</span>
                <span className="text-sm text-white">{formatScore(trustScore.score)}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-500">Level</span>
                <span className="text-sm text-white">{trustScore.level}</span>
              </div>
              <p className="text-sm text-slate-300">{trustScore.summary}</p>
            </div>
          </div>

          <div className="rounded-3xl border border-white/10 bg-slate-950/70 p-4">
            <h3 className="text-sm font-semibold uppercase tracking-[0.3em] text-slate-400">Observability Gaps</h3>
            <div className="mt-3 space-y-3 text-sm text-slate-200">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.3em] text-slate-500">Missing Critical Signals</p>
                <ul className="mt-2 space-y-1 text-sm text-slate-200">
                  {observabilityGaps.missing_critical_signals.length
                    ? observabilityGaps.missing_critical_signals.map((item) => <li key={item}>- {toText(item)}</li>)
                  : <li className="text-slate-500">No missing critical telemetry detected.</li>}
                </ul>
              </div>
              <p className="text-sm text-slate-300">{observabilityGaps.impact_on_confidence}</p>
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.3em] text-slate-500">Recommended Instrumentation</p>
                <ul className="mt-2 space-y-1 text-sm text-slate-200">
                  {observabilityGaps.recommended_instrumentation_steps.length
                    ? observabilityGaps.recommended_instrumentation_steps.map((item) => <li key={item}>- {toText(item)}</li>)
                  : <li className="text-slate-500">No immediate instrumentation steps.</li>}
                </ul>
              </div>
              <p className="text-sm text-slate-300">{observabilityGaps.summary}</p>
            </div>
          </div>
        </div>

        <div className="mt-6 rounded-3xl border border-white/10 bg-slate-950/70 p-4">
          <h3 className="text-sm font-semibold uppercase tracking-[0.3em] text-slate-400">Incident Cluster</h3>
          {incidentCluster ? (
            <div className="mt-3 space-y-2 text-sm text-slate-200">
              <p className="text-sm text-white">{incidentCluster.cluster_label}</p>
              <p className="text-xs text-slate-400">{incidentCluster.cluster_reason}</p>
              <p className="text-xs text-slate-500">
                Recurring Pattern: {incidentCluster.recurring_pattern ? "Yes" : "No"}
              </p>
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.3em] text-slate-500">Related Incidents</p>
                <ul className="mt-2 space-y-1 text-sm text-slate-200">
                  {incidentCluster.related_incident_ids.length
                    ? incidentCluster.related_incident_ids.map((item) => <li key={item}>- {item}</li>)
                    : <li className="text-slate-500">No related incidents detected.</li>}
                </ul>
              </div>
            </div>
          ) : (
            <p className="mt-3 text-sm text-slate-500">No cluster match found for this incident.</p>
          )}
        </div>

        <div className="mt-6 grid gap-6 xl:grid-cols-2">
          <div className="rounded-3xl border border-white/10 bg-slate-950/70 p-4">
            <h3 className="text-sm font-semibold uppercase tracking-[0.3em] text-slate-400">Log Summary</h3>
            {logSummary ? (
              <div className="mt-3 space-y-3 text-sm text-slate-200">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-xs text-slate-400">Key Error</span>
                  <span className="text-sm text-white">{toText(logSummary.key_error)}</span>
                </div>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-xs text-slate-400">Occurrences</span>
                  <span className="text-sm text-white">{logSummary.occurrence_count}</span>
                </div>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-xs text-slate-400">Affected Service</span>
                  <span className="text-sm text-white">{toText(logSummary.affected_service)}</span>
                </div>
                {logSummary.sample_log_line ? (
                  <div className="rounded-2xl border border-white/10 bg-slate-900/60 p-3 text-xs text-slate-300">
                    {toText(logSummary.sample_log_line)}
                  </div>
                ) : null}
                <p className="text-sm text-slate-300">{toText(logSummary.log_summary_text)}</p>
              </div>
            ) : (
              <p className="mt-3 text-sm text-slate-500">No log anomalies summarized for this incident.</p>
            )}
          </div>

          <div className="rounded-3xl border border-white/10 bg-slate-950/70 p-4">
            <h3 className="text-sm font-semibold uppercase tracking-[0.3em] text-slate-400">Impact Summary</h3>
            <div className="mt-3 space-y-3 text-sm text-slate-200">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-xs text-slate-400">Primary Service</span>
                <span className="text-sm text-white">{toText(impactSummary.primary_service)}</span>
              </div>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-xs text-slate-400">Severity</span>
                <span className="text-sm text-white">{toText(impactSummary.severity_label)}</span>
              </div>
              <div className="rounded-2xl border border-white/10 bg-slate-900/60 p-3 text-sm text-slate-200">
                {toText(impactSummary.summary_text)}
              </div>
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.3em] text-slate-500">Secondary Services</p>
                <ul className="mt-2 space-y-1 text-sm text-slate-200">
                  {impactSummary.secondary_services.length
                    ? impactSummary.secondary_services.map((item) => <li key={item}>- {toText(item)}</li>)
                    : <li className="text-slate-500">No secondary services identified.</li>}
                </ul>
              </div>
              <div className="text-xs text-slate-400">Estimated user impact: {toText(impactSummary.estimated_user_impact)}</div>
            </div>
          </div>
        </div>

        <div className="mt-6 rounded-3xl border border-white/10 bg-slate-950/80 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold uppercase tracking-[0.3em] text-slate-400">AI Reasoning</h3>
              <p className="mt-1 text-xs text-slate-500">
                AI reasoning runs on demand and may consume LLM tokens.
              </p>
            </div>
            <button
              type="button"
              onClick={handleRunReasoning}
              disabled={!canRunReasoning}
              className={`rounded-full px-4 py-2 text-xs font-semibold uppercase tracking-[0.3em] ${
                canRunReasoning ? "bg-cyan-500 text-slate-950 hover:bg-cyan-400" : "bg-slate-700 text-slate-300"
              }`}
            >
              {derivedStatus === "failed" ? "Retry Reasoning" : derivedStatus === "completed" ? "Re-run Reasoning" : "Run Reasoning"}
            </button>
          </div>
          <div className="mt-3 text-sm text-slate-300">
            Status: <span className="font-semibold text-white">{formatReasoningStatus(derivedStatus, reasoningBusy)}</span>
          </div>
          {reasoningError ? (
            <p className="mt-2 text-xs text-rose-300">Last error: {reasoningError}</p>
          ) : null}
        </div>

        <div className="mt-6 grid gap-6 xl:grid-cols-2">
          <div className="rounded-3xl border border-white/10 bg-slate-950/70 p-4">
            <h3 className="text-sm font-semibold uppercase tracking-[0.3em] text-slate-400">Confidence Explanation</h3>
            <div className="mt-3 text-sm text-slate-200">
              <p>Score: {formatScore(confidenceDetails.score ?? reasoning?.confidence_score ?? 0)}</p>
              <p>Level: {toText(confidenceDetails.level || "unknown")}</p>
              <p className="mt-2 text-slate-400">{toText(confidenceDetails.explanation_text || "No explanation yet.")}</p>
            </div>
            <div className="mt-4 grid gap-3 lg:grid-cols-2">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.3em] text-slate-500">Supporting Factors</p>
                <ul className="mt-2 space-y-1 text-sm text-slate-200">
                  {Array.isArray(confidenceDetails.supporting_factors) && confidenceDetails.supporting_factors.length
                    ? confidenceDetails.supporting_factors.map((item) => <li key={item}>- {toText(item)}</li>)
                    : <li className="text-slate-500">No data</li>}
                </ul>
              </div>
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.3em] text-slate-500">Weakening Factors</p>
                <ul className="mt-2 space-y-1 text-sm text-slate-200">
                  {Array.isArray(confidenceDetails.weakening_factors) && confidenceDetails.weakening_factors.length
                    ? confidenceDetails.weakening_factors.map((item) => <li key={item}>- {toText(item)}</li>)
                    : <li className="text-slate-500">No data</li>}
                </ul>
              </div>
            </div>
          </div>

          <div className="rounded-3xl border border-white/10 bg-slate-950/70 p-4">
            <h3 className="text-sm font-semibold uppercase tracking-[0.3em] text-slate-400">Reasoning History</h3>
            <div className="mt-3 space-y-2 text-sm text-slate-200">
              {reasoningHistory.length ? reasoningHistory.map((run) => (
                <button
                  key={run.reasoning_run_id}
                  type="button"
                  onClick={() => handleSelectRun(run)}
                  className={`w-full rounded-2xl border border-white/10 px-3 py-2 text-left ${
                    runDetail?.reasoning_run_id === run.reasoning_run_id ? "bg-slate-800/70" : "bg-slate-900/50"
                  }`}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-xs text-slate-400">{new Date(run.started_at).toLocaleString()}</span>
                    <span className="text-xs uppercase tracking-[0.2em] text-cyan-300">{toText(run.status)}</span>
                  </div>
                  <div className="mt-1 text-sm text-white">{toText(run.summary || "No summary")}</div>
                  <div className="mt-1 text-xs text-slate-400">
                    {toText(run.provider)} / {toText(run.model)} / {toText(run.trigger_type)}
                  </div>
                </button>
              )) : (
                <p className="text-slate-500">No reasoning history yet.</p>
              )}
            </div>
            {runDetail ? (
              <div className="mt-4 rounded-2xl border border-white/10 bg-slate-900/60 p-3 text-sm text-slate-200">
                <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Selected Run</p>
                <p className="mt-2">{toText(runDetail.summary || "No summary")}</p>
                <p className="mt-2 text-xs text-slate-400">Confidence: {formatScore(runDetail.root_cause_confidence ?? 0)}</p>
              </div>
            ) : null}
          </div>
        </div>

        <div className="mt-6 rounded-3xl border border-white/10 bg-slate-950/70 p-4">
          <h3 className="text-sm font-semibold uppercase tracking-[0.3em] text-slate-400">Related Incidents</h3>
          <div className="mt-3 space-y-2 text-sm text-slate-200">
            {correlations.length ? correlations.map((item) => (
              <div key={item.incident_id} className="rounded-2xl border border-white/10 bg-slate-900/60 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-xs text-slate-400">{new Date(item.timestamp).toLocaleString()}</span>
                  <span className="text-xs uppercase tracking-[0.2em] text-cyan-300">{formatScore(item.correlation_score)}</span>
                </div>
                <div className="mt-1 text-sm text-white">{toText(item.root_cause_summary || item.incident_id)}</div>
                <div className="mt-1 text-xs text-slate-400">{toText(item.correlation_reason || "related signal pattern")}</div>
              </div>
            )) : (
              <p className="text-slate-500">No related incidents found yet.</p>
            )}
          </div>
        </div>

        <div className="mt-6 grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
          <RichSection
            title="Incident Summary"
            content={`${currentIncident.incident_type || "observed"} incident on ${currentIncident.service} with anomaly score ${anomalyScore}.`}
          />
          <RichSection title="Reasoning Summary" content={reasoning?.root_cause || "Reasoning pending"} />
          <RichList title="Signals Detected" items={currentIncident.signals || []} />
          <RichList title="Causal Propagation Chain" items={reasoning?.causal_chain || []} />
          <RichList title="Suggested Actions" items={prioritizedActions.map((item) => item.label)} />
          <RichList title="Propagation Path" items={reasoning?.propagation_path || currentIncident.dependency_chain || []} />
          <RichList title="Impacted Services" items={impactedServices} />
          <RichList title="Missing Telemetry Signals" items={reasoning?.missing_telemetry_signals || []} />
          <RichList title="Telemetry Evidence" items={telemetryEvidence} />
        </div>

        <div className="mt-6 grid gap-4 lg:grid-cols-2">
          <InfoCard title="Cluster At-Risk Services" value={clusterReport?.at_risk_services ?? 0} />
          <InfoCard title="Missing Resource Limits" value={clusterReport?.missing_resource_limits ?? 0} />
        </div>

        <div className="mt-6 grid gap-6 xl:grid-cols-2">
          <RichList
            title="Change Timeline"
            items={(Array.isArray(changes) ? changes : [])
              .slice(0, 5)
              .map((item) => `${new Date(item.timestamp).toLocaleString()} - ${item.change_type} ${item.resource_type}/${item.resource_name}`)}
          />
          <RichList
            title="SLO Status"
            items={(Array.isArray(sloStatus) ? sloStatus : [])
              .map((item) => `${item.slo_type}: ${item.slo_status} (${Number(item.error_budget_remaining || 0).toFixed(1)}% budget)`)
            }
          />
          <RichList
            title="Runbook Suggestions"
            items={(Array.isArray(runbooks) ? runbooks : [])
              .slice(0, 3)
              .flatMap((runbook) => (Array.isArray(runbook.steps) ? runbook.steps.slice(0, 4) : []))
            }
          />
          <RichSection
            title="Observability Coverage Score"
            content={`Score: ${Number(observabilityReport?.observability_coverage_score ?? 0).toFixed(2)} | Traces: ${observabilityReport?.services_with_traces ?? 0}/${observabilityReport?.services_discovered ?? 0} | Metrics: ${observabilityReport?.services_with_metrics ?? 0}/${observabilityReport?.services_discovered ?? 0} | Logs: ${observabilityReport?.services_with_logs ?? 0}/${observabilityReport?.services_discovered ?? 0}`}
          />
        </div>

        <div className="mt-6 rounded-3xl border border-white/10 bg-slate-950/70 p-4">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold uppercase tracking-[0.3em] text-slate-400">Telemetry Charts</h3>
            <span className="text-xs text-slate-500">Timeline-derived values</span>
          </div>
          <div className="grid grid-cols-8 items-end gap-3">
            {chartPoints.map((point, index) => (
              <div key={`${point.kind}-${index}`} className="flex flex-col items-center gap-2">
                <div
                  className="w-full rounded-t-2xl bg-gradient-to-t from-cyan-500 to-orange-400"
                  style={{ height: `${Math.max(16, Math.min(160, point.value * 2))}px` }}
                />
                <span className="text-[10px] text-slate-500">{point.ts}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <IncidentTable
        incidents={incidentList}
        selectedIncidentId={currentIncident.incident_id}
        onOpenIncident={handleOpenIncident}
        emptyHint="No incidents available for this time range."
      />

      <div className="rounded-3xl border border-white/10 bg-slate-900/60 p-6">
        <h3 className="text-lg font-semibold text-white">Incident History</h3>
        <div className="mt-4 space-y-3">
          {incidentHistory.length ? incidentHistory.map((item) => (
            <div key={item.incident_id} className="rounded-2xl border border-white/10 bg-slate-950/70 p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <span className="text-sm font-medium text-white">{toText(item.service || "service")}</span>
                <span className="text-xs uppercase tracking-[0.3em] text-slate-500">{toText(item.severity || "unknown")}</span>
              </div>
              <p className="mt-2 text-xs text-slate-400">{new Date(item.timestamp).toLocaleString()}</p>
              <p className="mt-2 text-sm text-slate-300">{toText(item.root_cause_summary || "Previous incident detected.")}</p>
              <p className="mt-2 text-xs text-slate-500">Anomaly score: {formatScore(item.anomaly_score)}</p>
            </div>
          )) : (
            <p className="text-sm text-slate-500">No prior incidents for this service yet.</p>
          )}
        </div>
      </div>

      <div className="rounded-3xl border border-white/10 bg-slate-900/60 p-6">
        <h3 className="text-lg font-semibold text-white">Incident Timeline</h3>
        <div className="mt-4 space-y-3">
          {incidentTimeline.length ? incidentTimeline.map((event, index) => (
            <div key={`${event.event_type}-${event.timestamp}-${index}`} className="rounded-2xl border border-white/10 bg-slate-950/70 p-4">
              <div className="flex items-center justify-between gap-4">
                <span className="text-sm font-medium text-white">{toText(event.label)}</span>
                <span className="text-xs uppercase tracking-[0.3em] text-slate-500">{toText(event.event_type)}</span>
              </div>
              {event.service ? <p className="mt-2 text-xs text-slate-400">Service: {toText(event.service)}</p> : null}
              <p className="mt-2 text-xs text-slate-500">{new Date(event.timestamp).toLocaleString()}</p>
            </div>
          )) : (
            <p className="text-sm text-slate-500">No timeline events available for this incident yet.</p>
          )}
        </div>
      </div>
    </section>
  );
}

function InfoCard({ title, value }) {
  return (
    <div className="rounded-3xl border border-white/10 bg-slate-950/70 p-4">
      <p className="text-xs font-semibold uppercase tracking-[0.3em] text-slate-500">{title}</p>
      <p className="mt-2 text-base text-white">{toText(value)}</p>
    </div>
  );
}

function RichSection({ title, content }) {
  return (
    <div className="rounded-3xl border border-white/10 bg-slate-950/70 p-4">
      <h3 className="text-sm font-semibold uppercase tracking-[0.3em] text-slate-400">{title}</h3>
      <p className="mt-3 text-sm leading-6 text-slate-200">{toText(content)}</p>
    </div>
  );
}

function RichList({ title, items }) {
  const normalizedItems = toList(items);
  return (
    <div className="rounded-3xl border border-white/10 bg-slate-950/70 p-4">
      <h3 className="text-sm font-semibold uppercase tracking-[0.3em] text-slate-400">{title}</h3>
      <ul className="mt-3 space-y-2 text-sm text-slate-200">
        {normalizedItems.length
          ? normalizedItems.map((item) => <li key={item}>- {toText(item)}</li>)
          : <li className="text-slate-500">No data</li>}
      </ul>
    </div>
  );
}

function SignalGroup({ title, items }) {
  const normalizedItems = toList(items);
  return (
    <div className="rounded-2xl border border-white/10 bg-slate-900/60 p-3">
      <p className="text-xs font-semibold uppercase tracking-[0.3em] text-slate-500">{title}</p>
      <ul className="mt-2 space-y-1 text-sm text-slate-200">
        {normalizedItems.length
          ? normalizedItems.map((item) => <li key={item}>- {toText(item)}</li>)
          : <li className="text-slate-500">No data</li>}
      </ul>
    </div>
  );
}

function formatScore(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "0.00";
  return numeric.toFixed(2);
}

function formatConfidenceLabel(value, fallback) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0) {
    return fallback;
  }
  const level = numeric >= 0.75 ? "High" : numeric >= 0.45 ? "Medium" : "Low";
  return `${numeric.toFixed(2)} (${level})`;
}

function formatWorkflowStatus(value) {
  if (!value) return "Open";
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatTimestamp(value) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return "—";
  }
}

function formatReasoningStatus(status, busy) {
  if (busy) return "Running...";
  switch (status) {
    case "pending":
      return "Pending";
    case "running":
      return "Running...";
    case "completed":
      return "Completed";
    case "failed":
      return "Failed";
    case "not_generated":
    default:
      return "Not generated";
  }
}

function toList(value) {
  if (Array.isArray(value)) return value.map((item) => toText(item));
  if (value === null || value === undefined || value === "") return [];
  return [toText(value)];
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

function filterTimelineEvents(events, filterQuery) {
  if (!filterQuery || !filterQuery.start || !filterQuery.end) return events;
  const start = new Date(filterQuery.start).getTime();
  const end = new Date(filterQuery.end).getTime();
  if (!Number.isFinite(start) || !Number.isFinite(end)) return events;
  return events.filter((event) => {
    const ts = new Date(event.timestamp).getTime();
    if (!Number.isFinite(ts)) return false;
    return ts >= start && ts <= end;
  });
}

function priorityColor(priority) {
  switch (priority) {
    case "high":
      return "text-rose-300";
    case "medium":
      return "text-amber-300";
    case "low":
    default:
      return "text-slate-400";
  }
}

function buildDecisionPanel(incident, reasoning, prioritizedActions) {
  const confidenceScore = Number(reasoning?.confidence_score ?? incident?.predictive_confidence ?? 0);
  const rootCause = reasoning?.root_cause_service || reasoning?.root_cause || incident?.root_cause_entity || "Pending";
  const anomalyScore = Number(incident?.anomaly_score ?? 0);
  const impactSummary =
    reasoning?.impact_assessment ||
    reasoning?.customer_impact ||
    (incident?.impacts?.length
      ? `Impacting ${incident.impacts.length} downstream services.`
      : `Observed ${incident?.incident_type || "incident"} on ${incident?.service || "service"} with anomaly score ${formatScore(anomalyScore)}.`);
  const immediateAction = prioritizedActions[0]?.label || `Inspect ${incident?.service || "service"} latency and error metrics.`;
  const nextActions = prioritizedActions.slice(1, 4).map((item) => item.label);
  const investigationSteps = buildInvestigationSteps(incident, reasoning, prioritizedActions);
  return {
    root_cause: rootCause,
    impact_summary: impactSummary,
    confidence_score: confidenceScore,
    immediate_action: immediateAction,
    next_actions: nextActions,
    investigation_steps: investigationSteps,
  };
}

function buildPrioritizedActions(incident, reasoning) {
  const rawActions = [
    ...(Array.isArray(reasoning?.recommended_actions) ? reasoning.recommended_actions : []),
    ...(Array.isArray(incident?.remediation_suggestions) ? incident.remediation_suggestions : []),
  ]
    .map((item) => toText(item))
    .filter(Boolean);
  const fallbackActions = buildFallbackActions(incident, reasoning);
  const unique = Array.from(new Set(rawActions.length ? rawActions : fallbackActions));
  const baseConfidence = Number(reasoning?.confidence_score ?? incident?.predictive_confidence ?? 0.5);
  const items = unique.map((action) => classifyAction(action, baseConfidence, reasoning, incident));
  items.sort((a, b) => {
    const priorityOrder = { high: 0, medium: 1, low: 2 };
    const p = priorityOrder[a.priority] - priorityOrder[b.priority];
    if (p !== 0) return p;
    return b.confidence - a.confidence;
  });
  return items;
}

function classifyAction(action, baseConfidence, reasoning, incident) {
  const normalized = action.toLowerCase();
  let priority = "medium";
  let estimatedEffort = "medium";
  let riskLevel = "medium";

  if (/(latency|error|availability|outage)/.test(normalized)) {
    priority = "high";
  }
  if (/(scale|restart|rollback|failover|throttle|partition|consumer|cache|evict)/.test(normalized)) {
    priority = "high";
  }
  if (/(inspect|verify|check|review|analyze|investigate|confirm|trace)/.test(normalized)) {
    if (priority !== "high") {
      priority = "low";
    }
  }
  if (/(upgrade|migrate|refactor|reindex)/.test(normalized)) {
    estimatedEffort = "high";
    riskLevel = "high";
  } else if (/(restart|rollback|failover|throttle)/.test(normalized)) {
    estimatedEffort = "medium";
    riskLevel = "high";
  } else if (/(scale|increase|decrease|limit|tune)/.test(normalized)) {
    estimatedEffort = "low";
    riskLevel = "medium";
  }

  const confidence = Math.max(0, Math.min(1, baseConfidence + (priority === "high" ? 0.05 : priority === "low" ? -0.1 : 0)));
  if (reasoning?.missing_telemetry_signals?.length && priority === "low") {
    estimatedEffort = "low";
    riskLevel = "low";
  }
  if (incident?.anomaly_score && incident.anomaly_score > 1.5 && priority === "medium") {
    priority = "high";
  }

  return {
    label: action,
    priority,
    confidence,
    estimated_effort: estimatedEffort,
    risk_level: riskLevel,
  };
}

function buildInvestigationSteps(incident, reasoning, prioritizedActions) {
  const steps = [];
  const missingSignals = Array.isArray(reasoning?.missing_telemetry_signals) ? reasoning.missing_telemetry_signals : [];
  missingSignals.forEach((signal) => {
    const item = toText(signal);
    if (item) steps.push(`Collect missing telemetry: ${item}`);
  });
  const lowPriority = prioritizedActions.filter((action) => action.priority === "low").map((action) => action.label);
  return Array.from(new Set([...steps, ...lowPriority])).slice(0, 5);
}

function buildFallbackActions(incident, reasoning) {
  const service = incident?.service || "service";
  const signals = toList(incident?.signals).join(", ");
  const actions = [
    `Inspect ${service} latency and error metrics.`,
    `Review recent deployments or configuration changes for ${service}.`,
  ];
  if (signals) {
    actions.push(`Validate anomaly signals: ${signals}.`);
  }
  if (Array.isArray(reasoning?.missing_telemetry_signals) && reasoning.missing_telemetry_signals.length) {
    actions.push("Fill missing telemetry signals to improve confidence.");
  }
  return actions;
}

function buildSignalSummary(incident, reasoning) {
  const signals = toList(incident?.signals);
  const correlated = toList(reasoning?.correlated_signals);
  const missing = toList(reasoning?.missing_telemetry_signals);
  const snapshot = incident?.telemetry_snapshot || {};
  const critical = [];
  const secondary = [];

  const combined = Array.from(new Set([...signals, ...correlated]));
  combined.forEach((signal) => {
    const normalized = signal.toLowerCase();
    if (/(latency|error|timeout|consumer lag|saturation|availability)/.test(normalized)) {
      critical.push(signal);
    } else {
      secondary.push(signal);
    }
  });

  if (Number(snapshot.p95_latency_ms || 0) > Number(snapshot.baseline_latency_ms || 0) * 1.5) {
    critical.push("p95 latency above baseline");
  }
  if (Number(snapshot.error_rate || 0) > Number(snapshot.baseline_error_rate || 0) * 1.5) {
    critical.push("error rate above baseline");
  }
  if (Number(snapshot.cpu_utilization || 0) > 0.8) {
    secondary.push("cpu pressure");
  }
  if (Number(snapshot.memory_utilization || 0) > 0.8) {
    secondary.push("memory pressure");
  }

  if ((Array.isArray(snapshot.trace_ids) ? snapshot.trace_ids.length : 0) === 0) {
    missing.push("distributed tracing");
  }
  if (Number(snapshot.log_count || 0) === 0) {
    missing.push("structured logs");
  }

  return {
    critical_signals: Array.from(new Set(critical)).slice(0, 6),
    secondary_signals: Array.from(new Set(secondary)).slice(0, 6),
    missing_signals: Array.from(new Set(missing)).slice(0, 6),
  };
}

function buildLogSummary(incident) {
  const snapshot = incident?.telemetry_snapshot || {};
  const logs = Array.isArray(snapshot.error_logs) ? snapshot.error_logs.filter(Boolean) : [];
  const logCount = Number(snapshot.log_count || logs.length || 0);
  if (!logs.length && !logCount) return null;

  const topLog = logs[0] ? toText(logs[0]) : "";
  const keyError = extractKeyError(topLog) || "Log anomaly detected";
  const sample = topLog ? truncateText(topLog, 160) : "";
  const service = incident?.service || incident?.root_cause_entity || "service";
  const summaryKey = keyError.toLowerCase().includes("detected") ? keyError : `${keyError} detected`;
  return {
    key_error: keyError,
    occurrence_count: logCount || logs.length,
    affected_service: service,
    sample_log_line: sample,
    log_summary_text: `Repeated ${summaryKey} in ${service} logs.`,
  };
}

function extractKeyError(line) {
  if (!line) return "";
  const patterns = [
    /exception[:\\s]+([^\\n]+)/i,
    /error[:\\s]+([^\\n]+)/i,
    /failed[:\\s]+([^\\n]+)/i,
  ];
  for (const pattern of patterns) {
    const match = line.match(pattern);
    if (match && match[1]) return match[1].trim();
  }
  return line.split(" ").slice(0, 6).join(" ");
}

function buildImpactSummary(incident, reasoning) {
  const impacts = Array.isArray(incident?.impacts) ? incident.impacts : [];
  const primaryService = reasoning?.root_cause_service || incident?.root_cause_entity || incident?.service || "service";
  const secondaryServices = impacts
    .map((impact) => (impact && typeof impact === "object" ? toText(impact.service) : ""))
    .filter((svc) => svc && svc !== primaryService);
  const severity = incident?.severity || (incident?.anomaly_score > 10 ? "high" : "medium");
  const summaryText = impacts.length
    ? `${primaryService} impact is propagating to ${secondaryServices.slice(0, 3).join(", ") || "downstream services"}.`
    : `Issue localized to ${primaryService} with potential downstream effects.`;
  const userImpact = reasoning?.customer_impact || (incident?.incident_type === "predictive" ? "Potential user slowdown" : "User impact possible");
  return {
    primary_service: primaryService,
    secondary_services: Array.from(new Set(secondaryServices)).slice(0, 6),
    summary_text: summaryText,
    estimated_user_impact: userImpact,
    severity_label: String(severity).toUpperCase(),
  };
}

function buildIncidentTimeline(incident, reasoning) {
  const events = [];
  if (incident?.timestamp) {
    events.push({
      timestamp: incident.timestamp,
      event_type: "incident_created",
      label: "Incident created",
      service: incident.service,
    });
  }
  if (incident?.anomaly_score) {
    events.push({
      timestamp: incident.timestamp,
      event_type: "anomaly_detected",
      label: "Anomaly detected",
      service: incident.service,
    });
  }
  if (Array.isArray(incident?.signals)) {
    incident.signals.forEach((signal) => {
      events.push({
        timestamp: incident.timestamp,
        event_type: "signal_detected",
        label: `Signal: ${signal}`,
        service: incident.service,
      });
    });
  }
  if (incident?.reasoning_requested_at) {
    events.push({
      timestamp: incident.reasoning_requested_at,
      event_type: "reasoning_triggered",
      label: "Reasoning triggered",
      service: incident.service,
    });
  }
  if (incident?.reasoning_updated_at && incident?.reasoning_status === "completed") {
    events.push({
      timestamp: incident.reasoning_updated_at,
      event_type: "reasoning_completed",
      label: "Reasoning completed",
      service: incident.service,
    });
  }

  const timelineEvents = Array.isArray(incident?.timeline_summary) ? incident.timeline_summary : [];
  timelineEvents.forEach((event) => {
    events.push({
      timestamp: event.timestamp || incident.timestamp,
      event_type: event.kind || "telemetry_event",
      label: event.title || "Telemetry event",
      service: event.entity || incident.service,
    });
  });

  return events
    .filter((event) => event.timestamp)
    .sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
}

function truncateText(value, limit) {
  const text = toText(value);
  if (text.length <= limit) return text;
  return `${text.slice(0, limit)}...`;
}

function buildIncidentCluster(currentIncident, allIncidents) {
  if (!currentIncident || !Array.isArray(allIncidents)) return null;
  const rootService = currentIncident.reasoning?.root_cause_service || currentIncident.root_cause_entity || currentIncident.service;
  const rootSignal = currentIncident.reasoning?.root_cause_signal || (currentIncident.signals ? currentIncident.signals[0] : "");
  const severity = currentIncident.severity || "medium";
  const windowMs = 6 * 60 * 60 * 1000;
  const currentTime = new Date(currentIncident.timestamp).getTime();
  const related = allIncidents.filter((item) => {
    if (!item || item.incident_id === currentIncident.incident_id) return false;
    const itemTime = new Date(item.timestamp).getTime();
    const withinWindow = Math.abs(itemTime - currentTime) <= windowMs;
    const serviceMatch = (item.root_cause_entity || item.service) === rootService;
    const signalMatch = Array.isArray(item.signals) && item.signals.includes(rootSignal);
    const severityMatch = item.severity === severity;
    return withinWindow && (serviceMatch || signalMatch || severityMatch);
  });
  if (!related.length) return null;
  const clusterId = `${rootService || "service"}:${rootSignal || "signal"}:${severity}`;
  const clusterReason = `Grouped by ${rootService || "service"} and ${rootSignal || "signal"} within 6 hours.`;
  return {
    cluster_id: clusterId,
    cluster_label: `${rootService || "Service"} - ${rootSignal || "Signal"} cluster`,
    cluster_reason: clusterReason,
    related_incident_ids: related.slice(0, 4).map((item) => item.incident_id),
    recurring_pattern: related.length >= 3,
  };
}

function buildIncidentHistory(currentIncident, allIncidents) {
  if (!currentIncident || !Array.isArray(allIncidents)) return [];
  const service = currentIncident.service || currentIncident.root_cause_entity;
  return allIncidents
    .filter((item) => item && item.incident_id !== currentIncident.incident_id)
    .filter((item) => (item.service || item.root_cause_entity) === service)
    .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))
    .slice(0, 6)
    .map((item) => ({
      incident_id: item.incident_id,
      timestamp: item.timestamp,
      service: item.service,
      severity: item.severity,
      anomaly_score: item.anomaly_score,
      root_cause_summary: item.reasoning?.root_cause || item.root_cause_entity || item.service,
    }));
}

function buildObservabilityGaps(incident, reasoning) {
  const missing = toList(reasoning?.missing_telemetry_signals);
  const criticalMissing = missing.filter((signal) => /tracing|logs|kafka|database/i.test(signal));
  const impactText = criticalMissing.length
    ? "Missing critical telemetry reduces confidence in dependency-level causality."
    : "No critical observability gaps detected.";
  const recommendations = criticalMissing.map((signal) => {
    const value = signal.toLowerCase();
    if (value.includes("tracing")) return `Enable distributed tracing for ${incident?.service || "service"}.`;
    if (value.includes("logs")) return `Add structured logs for ${incident?.service || "service"} error paths.`;
    if (value.includes("kafka")) return "Enable Kafka broker and consumer lag metrics.";
    if (value.includes("database")) return "Capture database latency and error metrics.";
    return `Improve telemetry for ${signal}.`;
  });
  return {
    missing_critical_signals: criticalMissing,
    impact_on_confidence: impactText,
    recommended_instrumentation_steps: recommendations.slice(0, 4),
    summary: criticalMissing.length
      ? "Focus on missing critical telemetry to improve diagnosis trust."
      : "Current telemetry coverage is sufficient for this incident.",
  };
}

function buildTrustScore(incident, reasoning, signalSummary, observabilityGaps) {
  const base = Number(reasoning?.confidence_score ?? incident?.predictive_confidence ?? 0.5);
  const criticalSignals = Array.isArray(signalSummary?.critical_signals) ? signalSummary.critical_signals.length : 0;
  const missingCritical = Array.isArray(observabilityGaps?.missing_critical_signals)
    ? observabilityGaps.missing_critical_signals.length
    : 0;
  let score = base + Math.min(0.1, criticalSignals * 0.03) - Math.min(0.2, missingCritical * 0.05);
  score = Math.max(0, Math.min(1, score));
  const level = score >= 0.75 ? "high" : score >= 0.45 ? "medium" : "low";
  const summary = missingCritical
    ? `Trust is ${level} because critical telemetry gaps remain.`
    : `Trust is ${level} based on confidence and signal coverage.`;
  return { score, level, summary };
}

function formatImpactedServices(value) {
  if (!Array.isArray(value)) return [];
  return value
    .map((impact) => {
      if (typeof impact === "string") return impact;
      if (!impact || typeof impact !== "object") return "";
      const service = toText(impact.service);
      const impactType = toText(impact.impact_type || "impact");
      const score = Number(impact.impact_score);
      if (!service) return "";
      if (Number.isFinite(score)) {
        return `${service} (${impactType}, score ${score.toFixed(2)})`;
      }
      return `${service} (${impactType})`;
    })
    .filter(Boolean);
}

function buildTelemetryEvidence(incident) {
  const snapshot = incident?.telemetry_snapshot || {};
  const lines = [];
  const requestCount = Number(snapshot.request_count || 0);
  const errorRate = Number(snapshot.error_rate || 0);
  const p95 = Number(snapshot.p95_latency_ms || 0);
  const cpu = Number(snapshot.cpu_utilization || 0);
  const memory = Number(snapshot.memory_utilization || 0);
  const logCount = Number(snapshot.log_count || 0);
  const traceCount = Array.isArray(snapshot.trace_ids) ? snapshot.trace_ids.length : 0;
  if (Number.isFinite(requestCount)) lines.push(`Requests observed: ${requestCount}`);
  if (Number.isFinite(errorRate)) lines.push(`Error rate: ${errorRate.toFixed(4)}`);
  if (Number.isFinite(p95)) lines.push(`P95 latency: ${p95.toFixed(2)} ms`);
  if (Number.isFinite(cpu)) lines.push(`CPU utilization: ${cpu.toFixed(2)}`);
  if (Number.isFinite(memory)) lines.push(`Memory utilization: ${memory.toFixed(2)}`);
  if (Number.isFinite(logCount)) lines.push(`Log events: ${logCount}`);
  lines.push(`Trace IDs sampled: ${traceCount}`);
  const highlights = snapshot.metric_highlights && typeof snapshot.metric_highlights === "object" ? snapshot.metric_highlights : {};
  const metricHighlights = Object.entries(highlights)
    .slice(0, 5)
    .map(([name, value]) => `${name}: ${Number(value).toFixed(4)}`);
  return lines.concat(metricHighlights);
}
