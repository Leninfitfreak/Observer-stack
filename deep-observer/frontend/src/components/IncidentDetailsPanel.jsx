import { useEffect, useState } from "react";
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

const MAX_REASONING_POLL_ATTEMPTS = 45;

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
      })
      .catch(console.error);
  }, [incident, filterQuery]);

  const chartPoints = timeline
    .filter((event) => Number.isFinite(Number(event?.value)))
    .slice(-8)
    .map((event) => ({
      ...event,
      ts: new Date(event.timestamp).toLocaleTimeString(),
      value: Number(event.value),
    }));

  const currentIncident = activeIncident || incident;
  const reasoning = currentIncident?.reasoning;
  const canonicalEvidence = buildCanonicalIncidentEvidence({
    incident: currentIncident,
    timeline,
    reasoning,
    correlations,
    incidentHistory,
  });
  const anomalyScore = formatScore(currentIncident?.anomaly_score);
  const derivedStatus = reasoningStatus || currentIncident?.reasoning_status || (reasoning ? "completed" : "not_generated");
  const runDetail = selectedRun && selectedRun.reasoning_run_id ? selectedRun : null;
  const canRunReasoning =
    Boolean(currentIncident) &&
    canonicalEvidence.scope.scope_complete &&
    ["not_generated", "failed", "completed"].includes(derivedStatus) &&
    !reasoningBusy;
  const confidenceDetails = canonicalEvidence.confidence_details;
  const prioritizedActions = canonicalEvidence.prioritized_actions;
  const decisionPanel = canonicalEvidence.decision_panel;
  const signalSummary = canonicalEvidence.signal_summary;
  const logSummary = canonicalEvidence.log_summary;
  const impactSummary = canonicalEvidence.impact_summary;
  const incidentTimeline = canonicalEvidence.incident_timeline;
  const observabilityGaps = canonicalEvidence.observability_gaps;
  const trustScore = canonicalEvidence.trust_score;
  const telemetryAudit = canonicalEvidence.telemetry_audit;
  const telemetryEvidence = canonicalEvidence.telemetry_evidence;
  const impactedServices = canonicalEvidence.impacted_services;
  const scope = canonicalEvidence.scope;
  const scopedRunbook = canonicalEvidence.runbook;
  const workflowStatus = (currentIncident?.workflow_status || "open").toLowerCase();
  const reasoningReady = canonicalEvidence.reasoning_ready;

  const refreshIncident = async () => {
    if (!currentIncident?.incident_id) return null;
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
    if (attempt > MAX_REASONING_POLL_ATTEMPTS) return;
    const updated = await refreshIncident();
    const status = updated?.reasoning_status || derivedStatus;
    if (status === "completed" || status === "failed") return;
    setTimeout(() => {
      pollForReasoning(attempt + 1).catch(() => {});
    }, 3000);
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
      {!currentIncident ? (
        <div className="rounded-3xl border border-white/10 bg-slate-900/60 p-6 text-sm text-slate-400">
          {emptyHint || "No incidents found for the selected filters."}
        </div>
      ) : (
        <div className="rounded-3xl border border-white/10 bg-slate-900/60 p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.3em] text-cyan-300">Incident Details Panel</p>
            <h2 className="mt-2 text-2xl font-semibold text-white">{scope.service || currentIncident.service || "Unknown service"}</h2>
            <p className="mt-1 text-sm text-slate-400">
              {scope.cluster_label} / {scope.namespace_label} / {new Date(currentIncident.timestamp).toLocaleString()}
            </p>
            {!scope.scope_complete ? (
              <p className="mt-2 text-xs text-amber-300">
                Scope incomplete: {scope.scope_warnings.join(" | ")}
              </p>
            ) : null}
          </div>
          <div className="rounded-3xl border border-white/10 bg-slate-950/80 px-4 py-3 text-right">
            <div className="text-xs uppercase tracking-[0.3em] text-slate-400">Anomaly Score</div>
            <div className="mt-1 text-2xl font-semibold text-white">{anomalyScore}</div>
          </div>
        </div>

        <div className="mt-6 grid gap-4 lg:grid-cols-2">
          <InfoCard title="Root Cause Service" value={reasoningReady ? (reasoning?.root_cause_service || currentIncident.root_cause_entity || "Pending") : "Not generated"} />
          <InfoCard title="Root Cause Signal" value={reasoningReady ? (reasoning?.root_cause_signal || toList(currentIncident.signals).join(", ")) : "Not generated"} />
          <InfoCard title="Customer Impact" value={reasoningReady ? (reasoning?.customer_impact || reasoning?.impact_assessment || "Pending") : "Awaiting reasoning"} />
          <InfoCard title="Observability Score" value={`${canonicalEvidence.observability_score}%`} />
          <InfoCard title="Service Health Score" value={`${formatScore(serviceHealth?.health_score ?? 0)} / 100`} />
          <InfoCard
            title="Root Cause Confidence"
            value={formatConfidenceLabel(reasoningReady ? reasoning?.confidence_score ?? 0 : 0, "Confidence pending")}
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
              {reasoningReady ? `Confidence ${formatScore(decisionPanel.confidence_score)}` : "Confidence Pending"}
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
            content={canonicalEvidence.incident_summary}
          />
          <RichSection title="Reasoning Summary" content={canonicalEvidence.reasoning_summary} />
          <RichList title="Signals Detected" items={signalSummary.critical_signals.concat(signalSummary.secondary_signals)} />
          <RichList title="Causal Propagation Chain" items={canonicalEvidence.causal_chain} />
          <RichList title="Suggested Actions" items={prioritizedActions.map((item) => item.label)} />
          <RichList title="Propagation Path" items={canonicalEvidence.propagation_path} />
          <RichList title="Impacted Services" items={impactedServices} />
          <RichList title="Missing Telemetry Signals" items={canonicalEvidence.missing_telemetry_signals} />
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
            title="Incident Guidance"
            items={scopedRunbook.incident_steps}
          />
          <RichSection
            title="Stack Observability Coverage"
            content={`Stack-wide score: ${Number(observabilityReport?.observability_coverage_score ?? 0).toFixed(2)} | Traces: ${observabilityReport?.services_with_traces ?? 0}/${observabilityReport?.services_discovered ?? 0} | Metrics: ${observabilityReport?.services_with_metrics ?? 0}/${observabilityReport?.services_discovered ?? 0} | Logs: ${observabilityReport?.services_with_logs ?? 0}/${observabilityReport?.services_discovered ?? 0}`}
          />
        </div>

        <div className="mt-6 rounded-3xl border border-white/10 bg-slate-950/70 p-4">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold uppercase tracking-[0.3em] text-slate-400">Telemetry Charts</h3>
            <span className="text-xs text-slate-500">Derived from incident-scoped telemetry only</span>
          </div>
          {chartPoints.length ? (
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
          ) : (
            <p className="text-sm text-slate-500">
              No chartable telemetry values are available for this incident scope.
            </p>
          )}
          {telemetryAudit.isSparse ? (
            <p className="mt-3 text-xs text-amber-300">
              Reasoning is operating with sparse telemetry. Confidence and recommendations are limited to the available evidence.
            </p>
          ) : null}
          {scopedRunbook.related_context_steps.length ? (
            <div className="mt-4 rounded-2xl border border-white/10 bg-slate-900/60 p-3">
              <p className="text-xs font-semibold uppercase tracking-[0.3em] text-slate-500">Related Context</p>
              <ul className="mt-2 space-y-1 text-sm text-slate-300">
                {scopedRunbook.related_context_steps.map((item) => <li key={item}>- {toText(item)}</li>)}
              </ul>
            </div>
          ) : null}
        </div>
        </div>
      )}

      {currentIncident ? (
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
      ) : null}

      {currentIncident ? (
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
      ) : null}
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

function buildCanonicalIncidentEvidence({ incident, timeline, reasoning, correlations, incidentHistory }) {
  const snapshot = incident?.telemetry_snapshot || {};
  const scope = normalizeIncidentScope(incident);
  const reasoningStatus = String(incident?.reasoning_status || "").toLowerCase();
  const hasCompletedReasoning = Boolean(reasoning) && reasoningStatus === "completed";
  const qualityBySignal = extractQualityBySignal(reasoning, snapshot);
  const impactedServices = formatImpactedServices(incident?.impacts);
  const directEvidence = {
    request_count: Number(snapshot.request_count || 0),
    log_count: Number(snapshot.log_count || 0),
    trace_sample_count: Array.isArray(snapshot.trace_ids) ? snapshot.trace_ids.length : 0,
    error_rate: Number(snapshot.error_rate || 0),
    p95_latency_ms: Number(snapshot.p95_latency_ms || 0),
    cpu_utilization: Number(snapshot.cpu_utilization || 0),
    memory_utilization: Number(snapshot.memory_utilization || 0),
    metric_highlights: snapshot.metric_highlights && typeof snapshot.metric_highlights === "object" ? snapshot.metric_highlights : {},
    timeline_event_count: Array.isArray(timeline) ? timeline.length : 0,
    direct_dependency_nodes: toList(incident?.dependency_chain),
  };

  const contextualEvidence = {
    traces_present: qualityBySignal.traces === "present" || qualityBySignal.traces === "sparse" || qualityBySignal.traces === "contextual",
    logs_present: qualityBySignal.logs === "present" || qualityBySignal.logs === "sparse" || qualityBySignal.logs === "contextual",
    metrics_present: qualityBySignal.metrics !== "missing",
    database_present: qualityBySignal.database === "present" || qualityBySignal.database === "sparse" || qualityBySignal.database === "contextual",
    messaging_present: qualityBySignal.messaging === "present" || qualityBySignal.messaging === "sparse" || qualityBySignal.messaging === "contextual",
    exception_present: qualityBySignal.exceptions === "present" || qualityBySignal.exceptions === "sparse" || qualityBySignal.exceptions === "contextual",
    infra_present: qualityBySignal.infra === "present" || qualityBySignal.infra === "sparse" || qualityBySignal.infra === "contextual",
    topology_present: qualityBySignal.topology === "present" || qualityBySignal.topology === "contextual",
  };

  const directDependencyText = directEvidence.direct_dependency_nodes.join(" ").toLowerCase();
  const directDatabasePresent = /\bdb:|database\b/.test(directDependencyText);
  const directMessagingPresent = /\bmessaging:|queue|topic|messag/.test(directDependencyText);
  const directExceptionPresent = Array.isArray(snapshot.error_logs) && snapshot.error_logs.length > 0;

  const telemetryAudit = {
    hasChartData: Array.isArray(timeline) && timeline.some((event) => Number.isFinite(Number(event?.value))),
    isSparse:
      !scope.scope_complete ||
      (directEvidence.request_count === 0 &&
        directEvidence.log_count === 0 &&
        directEvidence.trace_sample_count === 0 &&
        Object.keys(directEvidence.metric_highlights).length === 0),
    evidenceSignals:
      Number(directEvidence.request_count > 0) +
      Number(directEvidence.log_count > 0) +
      Number(directEvidence.trace_sample_count > 0) +
      Number(Object.keys(directEvidence.metric_highlights).length > 0) +
      Number(directDatabasePresent || contextualEvidence.database_present) +
      Number(directMessagingPresent || contextualEvidence.messaging_present),
    telemetryQuality: qualityBySignal,
  };

  const missingTelemetrySignals = buildCanonicalMissingTelemetrySignals(scope, directEvidence, contextualEvidence, qualityBySignal);
  const signalSummary = buildCanonicalSignalSummary(incident, reasoning, missingTelemetrySignals, qualityBySignal);
  const confidenceDetails = buildCanonicalConfidenceDetails(
    incident,
    reasoning,
    hasCompletedReasoning,
    scope,
    directEvidence,
    contextualEvidence,
    qualityBySignal,
    telemetryAudit,
  );
  const observabilityGaps = buildCanonicalObservabilityGaps(scope, missingTelemetrySignals, contextualEvidence);
  const trustScore = buildCanonicalTrustScore(reasoning, incident, hasCompletedReasoning, telemetryAudit, observabilityGaps);
  const prioritizedActions = buildCanonicalPrioritizedActions(incident, reasoning, hasCompletedReasoning, telemetryAudit, missingTelemetrySignals, scope);
  const decisionPanel = buildCanonicalDecisionPanel(incident, reasoning, hasCompletedReasoning, prioritizedActions, telemetryAudit, scope, impactedServices);
  const logSummary = buildCanonicalLogSummary(incident);
  const impactSummary = buildCanonicalImpactSummary(incident, reasoning, hasCompletedReasoning, telemetryAudit, impactedServices, scope);
  const incidentTimeline = buildCanonicalIncidentTimeline(incident, reasoning);
  const runbook = buildCanonicalRunbook(scope, hasCompletedReasoning, prioritizedActions, missingTelemetrySignals, correlations, incidentHistory);
  const observabilityScore = buildCanonicalObservabilityScore(directEvidence, contextualEvidence, scope, qualityBySignal);

  return {
    scope,
    direct_evidence: directEvidence,
    contextual_evidence: contextualEvidence,
    telemetry_audit: telemetryAudit,
    telemetry_evidence: buildCanonicalTelemetryEvidence(scope, directEvidence, contextualEvidence, qualityBySignal),
    missing_telemetry_signals: missingTelemetrySignals,
    signal_summary: signalSummary,
    confidence_details: confidenceDetails,
    observability_gaps: observabilityGaps,
    trust_score: trustScore,
    prioritized_actions: prioritizedActions,
    decision_panel: decisionPanel,
    log_summary: logSummary,
    impact_summary: impactSummary,
    incident_timeline: incidentTimeline,
    observability_score: Number.isFinite(observabilityScore) ? observabilityScore.toFixed(2) : "0.00",
    impacted_services: impactedServices,
    propagation_path: toList(reasoning?.propagation_path).length ? toList(reasoning?.propagation_path) : toList(incident?.dependency_chain),
    causal_chain: toList(reasoning?.causal_chain),
    reasoning_summary: buildCanonicalReasoningSummary(reasoning, hasCompletedReasoning, scope, telemetryAudit),
    incident_summary: buildCanonicalIncidentSummary(incident, scope, telemetryAudit),
    runbook,
    reasoning_ready: hasCompletedReasoning,
    reasoning_status: reasoningStatus || "not_generated",
  };
}

function buildCanonicalObservabilityScore(directEvidence, contextualEvidence, scope, qualityBySignal) {
  let score = 0;
  score += directEvidence.request_count > 0 || directEvidence.trace_sample_count > 0 ? 24 : qualityBySignal.traces === "contextual" ? 10 : 6;
  score += directEvidence.log_count > 0 ? 18 : qualityBySignal.logs === "contextual" ? 8 : contextualEvidence.logs_present ? 10 : 4;
  score += qualityBySignal.metrics === "present" ? 18 : qualityBySignal.metrics === "zero" ? 10 : 4;
  score += qualityBySignal.database === "contextual" ? 6 : contextualEvidence.database_present ? 10 : 4;
  score += qualityBySignal.messaging === "contextual" ? 6 : contextualEvidence.messaging_present ? 10 : 4;
  score += qualityBySignal.exceptions === "contextual" ? 6 : contextualEvidence.exception_present ? 10 : 4;
  score += qualityBySignal.infra === "contextual" ? 3 : contextualEvidence.infra_present ? 5 : 2;
  score += qualityBySignal.topology === "contextual" ? 3 : contextualEvidence.topology_present ? 5 : 2;
  if (!scope.scope_complete) {
    score = Math.min(score, 45);
  }
  return Math.max(0, Math.min(100, Number(score.toFixed(2))));
}

function normalizeIncidentScope(incident) {
  const rawScope = incident?.scope && typeof incident.scope === "object" ? incident.scope : {};
  const scopeWarnings = toList(rawScope.scope_warnings);
  return {
    incident_id: rawScope.incident_id || incident?.incident_id || "",
    cluster: rawScope.cluster || incident?.cluster || "",
    namespace: rawScope.namespace || incident?.namespace || "",
    service: rawScope.service || incident?.service || incident?.root_cause_entity || "",
    incident_type: rawScope.incident_type || incident?.incident_type || "observed",
    incident_window_start: rawScope.incident_window_start || incident?.telemetry_snapshot?.incident_window_start || incident?.timestamp || "",
    incident_window_end: rawScope.incident_window_end || incident?.telemetry_snapshot?.incident_window_end || incident?.timestamp || "",
    signal_set: Array.isArray(rawScope.signal_set) ? rawScope.signal_set : toList(incident?.signals),
    anomaly_score: Number(rawScope.anomaly_score ?? incident?.anomaly_score ?? 0),
    scope_complete: rawScope.scope_complete !== false && scopeWarnings.length === 0,
    scope_warnings: scopeWarnings,
    cluster_label: rawScope.cluster || incident?.cluster || "Unknown cluster",
    namespace_label: rawScope.namespace || incident?.namespace || "Unknown namespace",
  };
}

function extractQualityBySignal(reasoning, snapshot) {
  const summary = reasoning?.observability_summary || {};
  const raw = summary.quality_by_signal;
  if (raw && typeof raw === "string") {
    try {
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === "object") return parsed;
    } catch {
      // ignore parse failure
    }
  }
  if (snapshot?.telemetry_quality && typeof snapshot.telemetry_quality === "object") {
    return snapshot.telemetry_quality;
  }
  return {};
}

function buildCanonicalTelemetryEvidence(scope, directEvidence, contextualEvidence, qualityBySignal) {
  const lines = [
    `Selected incident scope: ${scope.service || "Unknown service"} / ${scope.namespace_label} / ${scope.cluster_label}`,
    `Incident window: ${formatTimestamp(scope.incident_window_start)} to ${formatTimestamp(scope.incident_window_end)}`,
    `Incident-scoped requests: ${directEvidence.request_count}`,
    `Incident-scoped logs: ${directEvidence.log_count}`,
    `Incident-scoped trace samples: ${directEvidence.trace_sample_count}`,
  ];
  if (Number.isFinite(directEvidence.error_rate)) {
    lines.push(`Incident-scoped error rate: ${directEvidence.error_rate.toFixed(4)}`);
  }
  if (Number.isFinite(directEvidence.p95_latency_ms)) {
    lines.push(`Incident-scoped p95 latency: ${directEvidence.p95_latency_ms.toFixed(2)} ms`);
  }
  Object.entries(qualityBySignal).forEach(([signal, status]) => {
    lines.push(`${signal} evidence quality: ${status}`);
  });
  if (contextualEvidence.database_present) {
    lines.push("Contextual database evidence is present in the scoped service window.");
  }
  if (contextualEvidence.messaging_present) {
    lines.push("Contextual messaging evidence is present in the scoped service window.");
  }
  if (contextualEvidence.topology_present) {
    lines.push("Contextual dependency topology is available for this incident scope.");
  }
  return lines;
}

function buildCanonicalMissingTelemetrySignals(scope, directEvidence, contextualEvidence, qualityBySignal) {
  const missing = [];
  if (!scope.scope_complete) {
    missing.push(`Incident scope is incomplete: ${scope.scope_warnings.join(", ")}`);
  }
  if (directEvidence.request_count === 0 && directEvidence.trace_sample_count === 0) {
    missing.push(
      contextualEvidence.traces_present
        ? "No incident-scoped traces were attached; only broader scoped trace context is available."
        : "No incident-scoped traces were found.",
    );
  }
  if (directEvidence.log_count === 0) {
    missing.push(
      contextualEvidence.logs_present
        ? "No incident-scoped logs were attached; only broader scoped log context is available."
        : "No incident-scoped logs were found.",
    );
  }
  if (qualityBySignal.metrics === "missing") {
    missing.push("No incident-scoped service metrics were found.");
  } else if (qualityBySignal.metrics === "zero") {
    missing.push("Service metrics are present but zero across the incident window.");
  }
  if (!contextualEvidence.exception_present) {
    missing.push("No exception evidence was found for the selected incident scope.");
  }
  if (!contextualEvidence.infra_present) {
    missing.push("No runtime host/container evidence was correlated for the selected incident scope.");
  }
  return Array.from(new Set(missing));
}

function buildCanonicalSignalSummary(incident, reasoning, missingTelemetrySignals, qualityBySignal) {
  const critical = [];
  const secondary = [];
  const missing = [...missingTelemetrySignals];
  const combined = Array.from(new Set([...toList(incident?.signals), ...toList(reasoning?.correlated_signals)]));
  combined.forEach((signal) => {
    const normalized = signal.toLowerCase();
    if (/(latency|error|timeout|availability|saturation|exception)/.test(normalized)) {
      critical.push(signal);
    } else {
      secondary.push(signal);
    }
  });
  if (qualityBySignal.database === "present" || qualityBySignal.database === "sparse" || qualityBySignal.database === "contextual") {
    secondary.push("database dependency evidence");
  }
  if (qualityBySignal.messaging === "present" || qualityBySignal.messaging === "sparse" || qualityBySignal.messaging === "contextual") {
    secondary.push("messaging dependency evidence");
  }
  return {
    critical_signals: Array.from(new Set(critical)).slice(0, 6),
    secondary_signals: Array.from(new Set(secondary)).slice(0, 6),
    missing_signals: Array.from(new Set(missing)).slice(0, 6),
  };
}

function buildCanonicalConfidenceDetails(incident, reasoning, hasCompletedReasoning, scope, directEvidence, contextualEvidence, qualityBySignal, telemetryAudit) {
  if (!hasCompletedReasoning) {
    return {
      score: 0,
      level: "pending",
      explanation_text:
        "Reasoning has not been generated for this incident yet. Confidence will be computed after a manual reasoning run from the same selected-incident evidence basis shown on this page.",
      supporting_factors: [
        `Selected incident scope: ${scope.service || "Unknown service"} / ${scope.namespace_label} / ${scope.cluster_label}`,
        `Direct evidence currently shows ${directEvidence.request_count} requests, ${directEvidence.log_count} logs, and ${directEvidence.trace_sample_count} sampled traces.`,
      ],
      weakening_factors: ["RCA confidence is unavailable until reasoning is generated."],
    };
  }
  const score = Number(reasoning?.confidence_score ?? incident?.predictive_confidence ?? 0);
  const supporting = [];
  const weakening = [];
  if (directEvidence.request_count > 0 || directEvidence.trace_sample_count > 0) {
    supporting.push(`Incident-scoped trace/request evidence is present (${directEvidence.request_count} requests, ${directEvidence.trace_sample_count} sampled traces).`);
  } else if (contextualEvidence.traces_present) {
    supporting.push("Broader scoped trace evidence is present, but it is contextual rather than direct incident evidence.");
  } else {
    weakening.push("No trace evidence was found for the selected incident scope.");
  }
  if (directEvidence.log_count > 0) {
    supporting.push(`Incident-scoped logs are present (${directEvidence.log_count} events).`);
  } else if (contextualEvidence.logs_present) {
    supporting.push("Broader scoped log evidence is present, but not directly attached to the selected incident snapshot.");
  } else {
    weakening.push("No logs were found for the selected incident scope.");
  }
  if (contextualEvidence.database_present) {
    supporting.push(
      directEvidence.direct_dependency_nodes.some((item) => /db:|database/i.test(item))
        ? "Database evidence is directly attached to the selected incident."
        : "Database evidence is available as contextual service-window evidence.",
    );
  }
  if (contextualEvidence.messaging_present) {
    supporting.push(
      directEvidence.direct_dependency_nodes.some((item) => /messaging:|queue|topic/i.test(item))
        ? "Messaging evidence is directly attached to the selected incident."
        : "Messaging evidence is available as contextual service-window evidence.",
    );
  }
  if (!scope.scope_complete) {
    weakening.push(`Incident scope is incomplete: ${scope.scope_warnings.join(", ")}.`);
  }
  if (qualityBySignal.metrics === "zero") {
    weakening.push("Metric values are present but zero across the selected incident window.");
  }
  if (telemetryAudit.isSparse) {
    weakening.push("Direct incident telemetry is sparse, so the RCA remains low-confidence.");
  }
  const level = score >= 0.75 ? "high" : score >= 0.45 ? "medium" : "low";
  const explanationText = telemetryAudit.isSparse
    ? "Confidence is limited because the selected incident has sparse direct telemetry. Contextual topology, database, or messaging evidence is called out separately when present."
    : "Confidence is based on the selected incident scope first, with broader scoped evidence labeled separately as contextual support.";
  return {
    score,
    level,
    explanation_text: explanationText,
    supporting_factors: Array.from(new Set(supporting)),
    weakening_factors: Array.from(new Set(weakening)),
  };
}

function buildCanonicalObservabilityGaps(scope, missingTelemetrySignals, contextualEvidence) {
  const criticalMissing = missingTelemetrySignals.filter((signal) => /trace|log|metric|exception|scope|runtime/i.test(signal));
  const recommendations = [];
  if (criticalMissing.some((item) => /trace/i.test(item))) {
    recommendations.push(`Ensure the selected incident scope for ${scope.service || "service"} includes direct trace correlation.`);
  }
  if (criticalMissing.some((item) => /log/i.test(item))) {
    recommendations.push(`Ensure structured logs are available for ${scope.service || "service"} within the selected incident window.`);
  }
  if (criticalMissing.some((item) => /metric/i.test(item))) {
    recommendations.push(`Ensure service metrics are queryable for ${scope.service || "service"} within the selected incident window.`);
  }
  if (criticalMissing.some((item) => /exception/i.test(item))) {
    recommendations.push("Capture exception evidence for the selected incident scope.");
  }
  if (!contextualEvidence.topology_present) {
    recommendations.push("Dependency topology is unavailable for this scope, so propagation analysis is limited.");
  }
  return {
    missing_critical_signals: criticalMissing,
    impact_on_confidence: criticalMissing.length
      ? "Confidence is reduced because selected-incident evidence is incomplete or only partially direct."
      : "Selected-incident telemetry coverage is internally consistent.",
    recommended_instrumentation_steps: recommendations.slice(0, 4),
    summary: criticalMissing.length
      ? "Improve missing selected-incident evidence before making stronger RCA claims."
      : "No critical observability gap is blocking selected-incident diagnosis.",
  };
}

function buildCanonicalTrustScore(reasoning, incident, hasCompletedReasoning, telemetryAudit, observabilityGaps) {
  if (!hasCompletedReasoning) {
    const observabilityScore = Math.max(0, Math.min(1, buildEvidenceCoverageScore(telemetryAudit, observabilityGaps)));
    const level = observabilityScore >= 0.75 ? "high" : observabilityScore >= 0.45 ? "medium" : "low";
    return {
      score: observabilityScore,
      level,
      summary:
        "Trust currently reflects evidence coverage only. RCA trust and confidence will be available after a manual reasoning run.",
    };
  }
  let score = Number(reasoning?.confidence_score ?? incident?.predictive_confidence ?? 0.2);
  score -= Math.min(0.25, observabilityGaps.missing_critical_signals.length * 0.05);
  if (telemetryAudit.isSparse) score -= 0.15;
  score = Math.max(0, Math.min(1, score));
  const level = score >= 0.75 ? "high" : score >= 0.45 ? "medium" : "low";
  return {
    score,
    level,
    summary: telemetryAudit.isSparse
      ? "Trust is limited because the selected incident has sparse direct telemetry and relies on contextual evidence."
      : `Trust is ${level} because panels are now grounded on a single selected-incident evidence contract.`,
  };
}

function buildCanonicalPrioritizedActions(incident, reasoning, hasCompletedReasoning, telemetryAudit, missingTelemetrySignals, scope) {
  if (!hasCompletedReasoning) {
    const evidenceFirst = [];
    if (telemetryAudit.isSparse) {
      evidenceFirst.push(`Review the selected incident window for ${scope.service || "the selected service"} before drawing conclusions.`);
    }
    evidenceFirst.push(`Inspect incident-scoped traces, metrics, and logs for ${scope.service || "the selected service"} in ${scope.namespace_label}.`);
    if (missingTelemetrySignals.some((item) => /log/i.test(item))) {
      evidenceFirst.push(`Check whether logs for ${scope.service || "the selected service"} are available in the selected incident window.`);
    }
    if (missingTelemetrySignals.some((item) => /trace/i.test(item))) {
      evidenceFirst.push(`Check whether trace correlation exists for the selected incident window before relying on broader service context.`);
    }
    evidenceFirst.push("Run reasoning manually when you want an RCA summary grounded on the evidence above.");
    return Array.from(new Set(evidenceFirst))
      .filter(Boolean)
      .slice(0, 5)
      .map((action) => ({
        label: action,
        priority: /run reasoning/i.test(action) ? "low" : telemetryAudit.isSparse ? "medium" : "high",
        confidence: 0,
        estimated_effort: "low",
        risk_level: "low",
      }));
  }
  const rawActions = [
    ...toList(reasoning?.recommended_actions),
    ...toList(incident?.remediation_suggestions),
  ];
  const fallback = [
    telemetryAudit.isSparse
      ? `Collect direct incident telemetry for ${scope.service || "service"} before making strong remediation changes.`
      : `Inspect the strongest anomaly signals for ${scope.service || "service"} within the selected incident window.`,
  ];
  if (missingTelemetrySignals.length) {
    fallback.push(`Close the biggest evidence gaps: ${missingTelemetrySignals.slice(0, 2).join(" | ")}`);
  }
  const unique = Array.from(new Set((rawActions.length ? rawActions : fallback).map((item) => toText(item)).filter(Boolean)));
  const items = unique.map((action) =>
    classifyAction(action, Number(reasoning?.confidence_score ?? incident?.predictive_confidence ?? 0.2), reasoning, incident),
  );
  items.sort((a, b) => {
    const priorityOrder = { high: 0, medium: 1, low: 2 };
    const priorityDiff = priorityOrder[a.priority] - priorityOrder[b.priority];
    if (priorityDiff !== 0) return priorityDiff;
    return b.confidence - a.confidence;
  });
  return items;
}

function buildCanonicalDecisionPanel(incident, reasoning, hasCompletedReasoning, prioritizedActions, telemetryAudit, scope, impactedServices) {
  if (!hasCompletedReasoning) {
    return {
      root_cause: "Reasoning has not been generated yet.",
      impact_summary:
        "This panel is showing selected-incident evidence only. No completed RCA is available until you run reasoning manually.",
      confidence_score: null,
      immediate_action: prioritizedActions[0]?.label || "Review selected-incident telemetry before making remediation changes.",
      next_actions: prioritizedActions.slice(1, 4).map((item) => item.label),
      investigation_steps: prioritizedActions.slice(0, 5).map((item) => item.label),
    };
  }
  return {
    root_cause: reasoning?.root_cause_service || reasoning?.root_cause || incident?.root_cause_entity || "Pending",
    impact_summary: telemetryAudit.isSparse
      ? "Direct selected-incident telemetry is sparse, so impact is partly inferred and labeled cautiously."
      : impactedServices.length
      ? `Impact is currently evidence-backed for ${impactedServices.length} impacted services.`
      : `Impact is currently centered on ${scope.service || "the selected service"}.`,
    confidence_score: Number(reasoning?.confidence_score ?? incident?.predictive_confidence ?? 0),
    immediate_action: prioritizedActions[0]?.label || "Review selected incident evidence before acting.",
    next_actions: prioritizedActions.slice(1, 4).map((item) => item.label),
    investigation_steps: prioritizedActions.slice(0, 5).map((item) => item.label),
  };
}

function buildCanonicalLogSummary(incident) {
  return buildLogSummary(incident);
}

function buildCanonicalImpactSummary(incident, reasoning, hasCompletedReasoning, telemetryAudit, impactedServices, scope) {
  return {
    primary_service: (hasCompletedReasoning ? reasoning?.root_cause_service : null) || incident?.root_cause_entity || scope.service || "service",
    secondary_services: impactedServices,
    summary_text: !hasCompletedReasoning
      ? `RCA has not been generated yet. Current impact is based only on selected-incident telemetry and discovered dependencies for ${scope.service || "the selected service"}.`
      : telemetryAudit.isSparse
      ? `Impact for ${scope.service || "this service"} is still uncertain because the selected incident has sparse direct evidence.`
      : reasoning?.impact_assessment || `Impact appears centered on ${scope.service || "the selected service"}.`,
    estimated_user_impact: reasoning?.customer_impact || "User impact is scoped to the selected incident only.",
    severity_label: String(incident?.severity || "unknown").toUpperCase(),
  };
}

function buildCanonicalIncidentTimeline(incident, reasoning) {
  return buildIncidentTimeline(incident, reasoning);
}

function buildCanonicalRunbook(scope, hasCompletedReasoning, prioritizedActions, missingTelemetrySignals, correlations, incidentHistory) {
  const incidentSteps = Array.from(new Set([
    ...prioritizedActions.slice(0, 4).map((item) => item.label),
    ...missingTelemetrySignals
      .filter((item) => /trace|log|metric|exception/i.test(item))
      .slice(0, 2)
      .map((item) => `Address evidence gap: ${item}`),
  ])).slice(0, 6);
  if (!hasCompletedReasoning) {
    incidentSteps.unshift("Review the selected-incident evidence panels before running reasoning.");
  }
  const relatedContextSteps = [];
  if (Array.isArray(correlations) && correlations.length) {
    relatedContextSteps.push(`Related incidents exist (${correlations.length}); review them separately before broadening the RCA.`);
  }
  if (Array.isArray(incidentHistory) && incidentHistory.length) {
    relatedContextSteps.push(`Historical incidents exist for ${scope.service || "this service"}; use them only as supporting context, not direct evidence.`);
  }
  return {
    incident_steps: incidentSteps,
    related_context_steps: relatedContextSteps,
  };
}

function buildCanonicalReasoningSummary(reasoning, hasCompletedReasoning, scope, telemetryAudit) {
  if (!scope.scope_complete) {
    return "Selected-incident RCA is limited because the incident scope is incomplete.";
  }
  if (hasCompletedReasoning && reasoning?.root_cause) {
    return toText(reasoning.root_cause);
  }
  if (!hasCompletedReasoning) {
    return "Reasoning has not been generated for this incident yet. The page is currently showing evidence only, not a completed RCA.";
  }
  if (telemetryAudit.isSparse) {
    return "Selected incident has sparse direct telemetry, so RCA remains low-confidence.";
  }
  return "Reasoning pending.";
}

function buildEvidenceCoverageScore(telemetryAudit, observabilityGaps) {
  let score = telemetryAudit.isSparse ? 0.35 : 0.65;
  score -= Math.min(0.2, observabilityGaps.missing_critical_signals.length * 0.03);
  return Math.max(0, Math.min(1, score));
}

function buildCanonicalIncidentSummary(incident, scope, telemetryAudit) {
  const base = `${scope.incident_type || "observed"} incident on ${scope.service || "unknown service"} with anomaly score ${formatScore(scope.anomaly_score)}.`;
  if (!scope.scope_complete) {
    return `${base} Scope is incomplete, so only scoped evidence that can be verified is shown.`;
  }
  if (telemetryAudit.isSparse) {
    return `${base} Direct incident telemetry is sparse and contextual evidence is labeled separately.`;
  }
  return `${base} Panels below use the same selected-incident evidence model.`;
}

function buildDecisionPanel(incident, reasoning, prioritizedActions) {
  const telemetryAudit = assessTelemetryData(incident, incident?.timeline_summary, reasoning);
  const confidenceScore = Number(reasoning?.confidence_score ?? incident?.predictive_confidence ?? 0);
  const rootCause = reasoning?.root_cause_service || reasoning?.root_cause || incident?.root_cause_entity || "Pending";
  const anomalyScore = Number(incident?.anomaly_score ?? 0);
  const impactSummary =
    reasoning?.impact_assessment ||
    reasoning?.customer_impact ||
    (telemetryAudit.isSparse
      ? "Telemetry is too sparse to support a strong incident impact narrative yet."
      : incident?.impacts?.length
      ? `Impacting ${incident.impacts.length} downstream services.`
      : `Observed ${incident?.incident_type || "incident"} on ${incident?.service || "service"} with anomaly score ${formatScore(anomalyScore)}.`);
  const immediateAction = prioritizedActions[0]?.label || (telemetryAudit.isSparse
    ? `Collect additional traces, logs, or metrics for ${incident?.service || "service"}.`
    : `Inspect ${incident?.service || "service"} latency and error metrics.`);
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
  const telemetryAudit = assessTelemetryData(incident, incident?.timeline_summary, reasoning);
  const rawActions = [
    ...(Array.isArray(reasoning?.recommended_actions) ? reasoning.recommended_actions : []),
    ...(Array.isArray(incident?.remediation_suggestions) ? incident.remediation_suggestions : []),
  ]
    .map((item) => toText(item))
    .filter(Boolean);
  const fallbackActions = buildFallbackActions(incident, reasoning, telemetryAudit);
  const unique = Array.from(new Set(rawActions.length ? rawActions : fallbackActions));
  const baseConfidence = Number(reasoning?.confidence_score ?? incident?.predictive_confidence ?? 0.2);
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

function buildFallbackActions(incident, reasoning, telemetryAudit = assessTelemetryData(incident, incident?.timeline_summary, reasoning)) {
  const service = incident?.service || "service";
  const signals = toList(incident?.signals).join(", ");
  const actions = telemetryAudit.isSparse
    ? [
        `Collect additional telemetry for ${service} before attempting remediation.`,
        `Review whether traces, logs, and service metrics are being emitted for ${service}.`,
      ]
    : [
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
  const telemetryQuality = snapshot.telemetry_quality && typeof snapshot.telemetry_quality === "object" ? snapshot.telemetry_quality : {};
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

  if (telemetryQuality.traces === "missing") {
    missing.push("distributed tracing");
  }
  if (telemetryQuality.logs === "missing") {
    missing.push("structured logs");
  }
  if (telemetryQuality.metrics === "missing") {
    missing.push("service-level metrics");
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
  const telemetryAudit = assessTelemetryData(incident, incident?.timeline_summary, reasoning);
  const impacts = Array.isArray(incident?.impacts) ? incident.impacts : [];
  const primaryService = reasoning?.root_cause_service || incident?.root_cause_entity || incident?.service || "service";
  const secondaryServices = impacts
    .map((impact) => (impact && typeof impact === "object" ? toText(impact.service) : ""))
    .filter((svc) => svc && svc !== primaryService);
  const severity = incident?.severity || (incident?.anomaly_score > 10 ? "high" : "medium");
  const summaryText = telemetryAudit.isSparse
    ? `Impact is unclear because telemetry for ${primaryService} is sparse.`
    : impacts.length
    ? `${primaryService} impact is propagating to ${secondaryServices.slice(0, 3).join(", ") || "downstream services"}.`
    : `Issue localized to ${primaryService} with potential downstream effects.`;
  const userImpact = reasoning?.customer_impact || (telemetryAudit.isSparse
    ? "User impact cannot be estimated confidently from the available telemetry."
    : incident?.incident_type === "predictive" ? "Potential user slowdown" : "User impact possible");
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
  const criticalMissing = missing.filter((signal) => /trac|span|logs?|metric|messag|queue|topic|db|database|dependency/i.test(signal));
  const impactText = criticalMissing.length
    ? "Missing critical telemetry reduces confidence in dependency-level causality."
    : "No critical observability gaps detected.";
  const recommendations = criticalMissing.map((signal) => {
    const value = signal.toLowerCase();
    if (value.includes("trac") || value.includes("span")) {
      return `Enable distributed tracing for ${incident?.service || "service"}.`;
    }
    if (value.includes("log")) {
      return `Add structured logs for ${incident?.service || "service"} error paths.`;
    }
    if (value.includes("messag") || value.includes("queue") || value.includes("topic")) {
      return "Capture messaging throughput, latency, and failure telemetry for the affected flow.";
    }
    if (value.includes("db") || value.includes("database") || value.includes("depend")) {
      return "Capture dependency latency, saturation, and error telemetry for the affected path.";
    }
    if (value.includes("metric")) {
      return `Add service-level metrics for ${incident?.service || "service"} latency, errors, and traffic.`;
    }
    return `Improve telemetry coverage for ${signal}.`;
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
  const telemetryAudit = assessTelemetryData(incident, incident?.timeline_summary, reasoning);
  const base = Number(reasoning?.confidence_score ?? incident?.predictive_confidence ?? 0.2);
  const criticalSignals = Array.isArray(signalSummary?.critical_signals) ? signalSummary.critical_signals.length : 0;
  const missingCritical = Array.isArray(observabilityGaps?.missing_critical_signals)
    ? observabilityGaps.missing_critical_signals.length
    : 0;
  let score = base + Math.min(0.1, criticalSignals * 0.03) - Math.min(0.2, missingCritical * 0.05);
  score = Math.max(0, Math.min(1, score));
  const level = score >= 0.75 ? "high" : score >= 0.45 ? "medium" : "low";
  const summary = telemetryAudit.isSparse
    ? "Trust is low because telemetry is sparse and the diagnosis is evidence-limited."
    : missingCritical
    ? `Trust is ${level} because critical telemetry gaps remain.`
    : `Trust is ${level} based on confidence and signal coverage.`;
  return { score, level, summary };
}

function assessTelemetryData(incident, timeline = [], reasoning) {
  const snapshot = incident?.telemetry_snapshot || {};
  const telemetryQuality = snapshot.telemetry_quality && typeof snapshot.telemetry_quality === "object" ? snapshot.telemetry_quality : {};
  const chartableTimeline = Array.isArray(timeline) ? timeline.filter((event) => Number.isFinite(Number(event?.value))) : [];
  const traceCount = Array.isArray(snapshot.trace_ids) ? snapshot.trace_ids.length : 0;
  const requestCount = Number(snapshot.request_count || 0);
  const logCount = Number(snapshot.log_count || 0);
  const cpu = Number(snapshot.cpu_utilization || 0);
  const memory = Number(snapshot.memory_utilization || 0);
  const highlights = snapshot.metric_highlights && typeof snapshot.metric_highlights === "object" ? Object.keys(snapshot.metric_highlights) : [];
  const missingSignals = Array.isArray(reasoning?.missing_telemetry_signals) ? reasoning.missing_telemetry_signals.length : 0;
  const evidenceSignals =
    Number(requestCount > 0) +
    Number(traceCount > 0) +
    Number(logCount > 0) +
    Number(cpu > 0 || memory > 0 || highlights.length > 0) +
    Number(chartableTimeline.length > 0);
  const qualityStates = Object.values(telemetryQuality);
  const explicitSparse = qualityStates.includes("sparse") || qualityStates.includes("stale") || qualityStates.includes("contradictory");
  return {
    hasChartData: chartableTimeline.length > 0,
    isSparse: explicitSparse || evidenceSignals <= 1 || missingSignals >= 3,
    evidenceSignals,
    telemetryQuality,
  };
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
  const telemetryQuality = snapshot.telemetry_quality && typeof snapshot.telemetry_quality === "object" ? snapshot.telemetry_quality : {};
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
  Object.entries(telemetryQuality).forEach(([signal, status]) => {
    lines.push(`${signal} telemetry: ${status}`);
  });
  const highlights = snapshot.metric_highlights && typeof snapshot.metric_highlights === "object" ? snapshot.metric_highlights : {};
  const metricHighlights = Object.entries(highlights)
    .slice(0, 5)
    .map(([name, value]) => `${name}: ${Number(value).toFixed(4)}`);
  return lines.concat(metricHighlights);
}
