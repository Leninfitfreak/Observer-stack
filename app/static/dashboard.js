/* global Chart */
(function () {
  const state = {
    incidentId: `INC-${Math.floor(Date.now() / 1000).toString().slice(-6)}`,
    incidentStart: new Date(),
    slaMinutes: 60,
    role: "Viewer",
    activeView: "ai",
    lastRaw: null,
    timeline: [],
    audit: [],
    charts: {},
    serviceHistory: {},
    signatures: {},
  };

  const els = {
    incidentId: document.getElementById("incidentId"),
    incidentStatus: document.getElementById("incidentStatus"),
    incidentSeverity: document.getElementById("incidentSeverity"),
    incidentStart: document.getElementById("incidentStart"),
    incidentDuration: document.getElementById("incidentDuration"),
    incidentOwner: document.getElementById("incidentOwner"),
    incidentSla: document.getElementById("incidentSla"),
    incidentRisk: document.getElementById("incidentRisk"),
    incidentBudget: document.getElementById("incidentBudget"),
    severityStrip: document.getElementById("severityStrip"),
    telemetryGrid: document.getElementById("telemetryGrid"),
    rootCause: document.getElementById("rootCause"),
    confidence: document.getElementById("confidence"),
    riskWindow: document.getElementById("riskWindow"),
    humanSummary: document.getElementById("humanSummary"),
    confidenceBreakdown: document.getElementById("confidenceBreakdown"),
    correlatedSignals: document.getElementById("correlatedSignals"),
    dependencyMap: document.getElementById("dependencyMap"),
    serviceBadges: document.getElementById("serviceBadges"),
    signatureRows: document.getElementById("signatureRows"),
    whyWarningRows: document.getElementById("whyWarningRows"),
    auditTrail: document.getElementById("auditTrail"),
    timeline: document.getElementById("timeline"),
    coverageScore: document.getElementById("coverageScore"),
    missingMetrics: document.getElementById("missingMetrics"),
    missingTraces: document.getElementById("missingTraces"),
    missingLogs: document.getElementById("missingLogs"),
    gapsList: document.getElementById("gapsList"),
    datasourceErrors: document.getElementById("datasourceErrors"),
    rawJson: document.getElementById("rawJson"),
    liveStatus: document.getElementById("liveStatus"),
    roleSelect: document.getElementById("roleSelect"),
    risingOnly: document.getElementById("risingOnly"),
    hideLowFreq: document.getElementById("hideLowFreq"),
    namespace: document.getElementById("namespace"),
    service: document.getElementById("service"),
    severity: document.getElementById("severity"),
    interval: document.getElementById("interval"),
    refreshBtn: document.getElementById("refreshBtn"),
    viewToggle: document.getElementById("viewToggle"),
    telemetrySection: document.getElementById("telemetrySection"),
    aiSection: document.getElementById("aiSection"),
    rawSection: document.getElementById("rawSection"),
    actionCenter: document.getElementById("actionCenter"),
  };

  let refreshTimer = null;
  let durationTimer = null;

  function fmtDate(d) {
    return d.toISOString().replace("T", " ").slice(0, 19) + "Z";
  }

  function fmtDuration(ms) {
    const sec = Math.max(0, Math.floor(ms / 1000));
    const h = String(Math.floor(sec / 3600)).padStart(2, "0");
    const m = String(Math.floor((sec % 3600) / 60)).padStart(2, "0");
    const s = String(sec % 60).padStart(2, "0");
    return `${h}:${m}:${s}`;
  }

  function hashCode(text) {
    let h = 0;
    for (let i = 0; i < text.length; i += 1) h = ((h << 5) - h) + text.charCodeAt(i);
    return `SIG-${Math.abs(h).toString(16).slice(0, 6).toUpperCase()}`;
  }

  function setLiveStatus(v, level) {
    els.liveStatus.textContent = v;
    els.liveStatus.style.color = level === "err" ? "var(--crit)" : level === "warn" ? "var(--warn)" : "var(--muted)";
  }

  function severityClass(s) {
    const x = String(s || "").toLowerCase();
    if (x.includes("critical")) return "critical";
    if (x.includes("high")) return "high";
    if (x.includes("medium") || x.includes("warning")) return "warning";
    return "healthy";
  }

  function riskPct(predicted) {
    const v = String(predicted || "").toLowerCase();
    if (v.includes("1h")) return 85;
    if (v.includes("24h")) return 60;
    return 18;
  }

  function deriveConfidenceBreakdown(data) {
    const ds = data.context?.datasource_errors || {};
    const missing = data.analysis?.missing_observability || [];
    const metricPct = ds.prometheus_metrics ? 20 : Math.max(25, 55 - (missing.length * 5));
    const logsPct = ds.loki ? 15 : 65;
    const tracePct = ds.jaeger ? 20 : 60;
    const histPct = Math.max(20, 70 - (missing.length * 6));
    return {
      metric: metricPct,
      logs: logsPct,
      trace: tracePct,
      historical: histPct,
    };
  }

  async function fetchReasoning(namespace, service, severity) {
    const qs = new URLSearchParams({ namespace, service, severity }).toString();
    const res = await fetch(`/api/reasoning/live?${qs}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  function pushTimeline(label, type) {
    const now = new Date();
    state.timeline.push({ label, type, ts: now.toISOString() });
    state.timeline = state.timeline.slice(-18);
  }

  function renderTimeline() {
    els.timeline.innerHTML = "";
    if (!state.timeline.length) {
      const x = document.createElement("div");
      x.className = "event";
      x.textContent = "No timeline events yet";
      els.timeline.appendChild(x);
      return;
    }
    state.timeline.forEach((event) => {
      const node = document.createElement("div");
      node.className = "event";
      node.innerHTML = `<strong>${event.label}</strong><small>${event.type} • ${event.ts.replace("T", " ").slice(0, 19)}Z</small>`;
      els.timeline.appendChild(node);
    });
  }

  function renderIncidentHeader(data) {
    const sevInput = els.severity.value;
    const comp = data.context?.component_summary || {};
    const status = comp.overall_status === "critical" ? "CRITICAL" : comp.overall_status === "warning" ? "INVESTIGATING" : "MITIGATING";
    const risk = riskPct(data.analysis?.risk_forecast?.predicted_breach_window);
    const burn = data.context?.slo?.error_budget_burn_rate_24h;
    const budget = Math.max(0, Math.round(100 - ((burn || 0) * 10)));
    const sevClass = severityClass(sevInput);
    const colors = { critical: "var(--crit)", high: "var(--high)", warning: "var(--warn)", healthy: "var(--ok)" };

    els.incidentId.textContent = state.incidentId;
    els.incidentStatus.textContent = status;
    els.incidentSeverity.textContent = sevInput.toUpperCase();
    els.incidentStart.textContent = fmtDate(state.incidentStart);
    els.incidentOwner.textContent = state.role === "Viewer" ? "oncall-sre" : `${state.role.toLowerCase()}-operator`;
    els.incidentRisk.textContent = `${risk}%`;
    els.incidentBudget.textContent = `${budget}%`;
    els.severityStrip.style.background = colors[sevClass] || "var(--warn)";
  }

  function renderDuration() {
    const now = new Date();
    const elapsed = now - state.incidentStart;
    const slaLeft = Math.max(0, state.slaMinutes * 60 * 1000 - elapsed);
    els.incidentDuration.textContent = fmtDuration(elapsed);
    els.incidentSla.textContent = fmtDuration(slaLeft);
  }

  function ensureHistory(service) {
    if (!state.serviceHistory[service]) {
      state.serviceHistory[service] = {
        ts: [],
        rps: [],
        err: [],
        p95: [],
        p99: [],
        cpu: [],
        mem: [],
        db: [],
        kafka: [],
        anomaly: [],
        deploy: [],
      };
    }
    return state.serviceHistory[service];
  }

  function capHistory(hist) {
    const maxPoints = 90;
    Object.keys(hist).forEach((k) => {
      if (Array.isArray(hist[k]) && hist[k].length > maxPoints) hist[k] = hist[k].slice(-maxPoints);
    });
  }

  function pushTelemetryPoint(service, context) {
    const hist = ensureHistory(service);
    const m = context.metrics || {};
    const d = context.deployment || {};
    const t = new Date().toLocaleTimeString();
    hist.ts.push(t);
    hist.rps.push(m.request_rate_rps_5m || 0);
    hist.err.push((m.error_rate_5xx_5m || 0) * 100);
    hist.p95.push((m.latency_p95_s_5m || 0) * 1000);
    hist.p99.push((m.latency_p99_s_5m || 0) * 1000);
    hist.cpu.push((m.cpu_usage_cores_5m || 0) * 100);
    hist.mem.push((m.memory_usage_bytes || 0) / (1024 * 1024));
    hist.db.push((m.db_connection_pool_usage_5m || 0) * 100);
    hist.kafka.push(m.kafka_consumer_lag || 0);
    hist.anomaly.push((m.anomalies || []).length > 0 ? 1 : 0);
    hist.deploy.push(d.deployment_changed_last_10m ? 1 : 0);
    capHistory(hist);
  }

  async function hydrateServiceTelemetry(components, baseNs, severity) {
    const jobs = (components || []).map(async (component) => {
      const svc = component.service;
      try {
        const data = await fetchReasoning(baseNs, svc, severity);
        pushTelemetryPoint(svc, data.context || {});
      } catch (e) {
        const hist = ensureHistory(svc);
        const t = new Date().toLocaleTimeString();
        hist.ts.push(t);
        hist.rps.push(0); hist.err.push(0); hist.p95.push(0); hist.p99.push(0);
        hist.cpu.push(0); hist.mem.push(0); hist.db.push(0); hist.kafka.push(0);
        hist.anomaly.push(0); hist.deploy.push(0);
        capHistory(hist);
      }
    });
    await Promise.all(jobs);
  }

  function chartConfig(hist, keyA, keyB, labelA, labelB) {
    const anomalyValues = hist[keyA].map((v, i) => (hist.anomaly[i] ? v : null));
    const deployValues = hist[keyA].map((v, i) => (hist.deploy[i] ? v : null));
    return {
      type: "line",
      data: {
        labels: hist.ts,
        datasets: [
          { label: labelA, data: hist[keyA], borderColor: "#60a5fa", borderWidth: 2, pointRadius: 0, tension: 0.25 },
          { label: labelB, data: hist[keyB], borderColor: "#f59e0b", borderWidth: 2, pointRadius: 0, tension: 0.25 },
          { label: "Anomaly", data: anomalyValues, borderColor: "#ef4444", backgroundColor: "#ef4444", pointRadius: 4, pointStyle: "triangle", showLine: false },
          { label: "Deployment", data: deployValues, borderColor: "#22c55e", backgroundColor: "#22c55e", pointRadius: 4, pointStyle: "rectRot", showLine: false },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: true, labels: { color: "#9fb2ce", boxWidth: 12 } } },
        scales: {
          x: { ticks: { color: "#8ea1be", maxTicksLimit: 7 }, grid: { color: "rgba(96,122,160,0.12)" } },
          y: { ticks: { color: "#8ea1be" }, grid: { color: "rgba(96,122,160,0.12)" } },
        },
      },
    };
  }

  function renderTelemetryCards(components) {
    els.telemetryGrid.innerHTML = "";
    (components || []).forEach((component) => {
      const service = component.service;
      const hist = ensureHistory(service);
      const card = document.createElement("div");
      card.className = "telemetry-card";
      card.innerHTML = `
        <h3>${service}</h3>
        <div class="telemetry-meta">
          <span class="pill ${component.status}">${component.status.toUpperCase()}</span>
          <span class="pill">RPS ${Number(hist.rps.at(-1) || 0).toFixed(2)}</span>
          <span class="pill">5xx ${Number(hist.err.at(-1) || 0).toFixed(2)}%</span>
          <span class="pill">p95 ${Math.round(hist.p95.at(-1) || 0)}ms</span>
          <span class="pill">p99 ${Math.round(hist.p99.at(-1) || 0)}ms</span>
          <span class="pill">CPU ${Math.round(hist.cpu.at(-1) || 0)}%</span>
          <span class="pill">Mem ${Math.round(hist.mem.at(-1) || 0)}MB</span>
          <span class="pill">DB ${Math.round(hist.db.at(-1) || 0)}%</span>
          <span class="pill">Kafka ${Math.round(hist.kafka.at(-1) || 0)}</span>
        </div>
        <div class="chart-wrap"><canvas id="chart-${service}"></canvas></div>
      `;
      els.telemetryGrid.appendChild(card);
      const canvas = card.querySelector("canvas");
      if (state.charts[service]) state.charts[service].destroy();
      state.charts[service] = new Chart(canvas, chartConfig(hist, "p95", "err", "p95 (ms)", "5xx (%)"));
    });
  }

  function renderAiPanels(data) {
    const analysis = data.analysis || {};
    const context = data.context || {};
    const componentSummary = context.component_summary || {};
    els.rootCause.textContent = analysis.probable_root_cause || "-";
    els.confidence.textContent = analysis.confidence_score || "-";
    els.riskWindow.textContent = analysis.risk_forecast?.predicted_breach_window || "-";
    els.humanSummary.textContent = analysis.human_summary || "-";

    const breakdown = deriveConfidenceBreakdown(data);
    els.confidenceBreakdown.innerHTML = [
      `<span class="chip">Metric: ${breakdown.metric}%</span>`,
      `<span class="chip">Logs: ${breakdown.logs}%</span>`,
      `<span class="chip">Trace: ${breakdown.trace}%</span>`,
      `<span class="chip">Historical Similarity: ${breakdown.historical}%</span>`,
    ].join("");

    els.correlatedSignals.innerHTML = "";
    (analysis.causal_chain || ["No correlated signals"]).forEach((x) => {
      const li = document.createElement("li");
      li.textContent = x;
      els.correlatedSignals.appendChild(li);
    });

    els.serviceBadges.innerHTML = "";
    (context.components || []).forEach((c) => {
      const span = document.createElement("span");
      span.className = `chip`;
      span.style.borderColor = c.status === "critical" ? "var(--crit)" : c.status === "warning" ? "var(--warn)" : "var(--ok)";
      span.textContent = `${c.service}: ${c.status}`;
      els.serviceBadges.appendChild(span);
    });
    renderDependencyMap(context.components || [], componentSummary.overall_status || "healthy");
  }

  function renderDependencyMap(components, overallStatus) {
    const nodeColor = (status) => status === "critical" ? "#ef4444" : status === "warning" ? "#f59e0b" : "#22c55e";
    const width = 700;
    const height = 280;
    const core = [{ id: "api-gateway", x: 120, y: 140 }, { id: "ai-observer", x: 350, y: 50 }, { id: "postgres", x: 580, y: 140 }];
    const apps = components.map((c, idx) => ({ id: c.service, x: 350, y: 110 + (idx * 70), status: c.status }));
    const links = [
      ["api-gateway", "product-service"],
      ["api-gateway", "order-service"],
      ["product-service", "postgres"],
      ["order-service", "postgres"],
      ["ai-observer", "product-service"],
      ["ai-observer", "order-service"],
    ];
    let svg = `<rect width="${width}" height="${height}" fill="#0a1324"/>`;
    const nodes = [...core, ...apps];
    links.forEach(([a, b]) => {
      const na = nodes.find((n) => n.id === a);
      const nb = nodes.find((n) => n.id === b);
      if (na && nb) svg += `<line x1="${na.x}" y1="${na.y}" x2="${nb.x}" y2="${nb.y}" stroke="#2c3f5f" stroke-width="2"/>`;
    });
    nodes.forEach((n) => {
      const status = n.status || (n.id === "ai-observer" ? overallStatus : "healthy");
      svg += `<circle cx="${n.x}" cy="${n.y}" r="23" fill="#11203b" stroke="${nodeColor(status)}" stroke-width="3"/>`;
      svg += `<text x="${n.x}" y="${n.y + 38}" fill="#b9cbe4" font-size="11" text-anchor="middle">${n.id}</text>`;
    });
    els.dependencyMap.innerHTML = svg;
  }

  function updateSignatureHistory(analysis) {
    const rows = analysis.error_log_prediction?.repeated_signatures || [];
    const now = new Date().toISOString();
    rows.forEach((row) => {
      const raw = String(row.signature || "");
      const count = Number(row.count || 0);
      const id = hashCode(raw);
      if (!state.signatures[id]) {
        state.signatures[id] = { id, raw, firstSeen: now, lastSeen: now, lastCount: count, count };
      } else {
        state.signatures[id].lastSeen = now;
        state.signatures[id].count = count;
      }
    });
  }

  function trend(current, previous) {
    if (current > previous) return "Increasing";
    if (current < previous) return "Decreasing";
    return "Stable";
  }

  function renderSignatureTable() {
    els.signatureRows.innerHTML = "";
    const risingOnly = els.risingOnly.checked;
    const hideLow = els.hideLowFreq.checked;
    const rows = Object.values(state.signatures)
      .map((s) => {
        const t = trend(s.count, s.lastCount);
        const errorType = s.raw.replace(/[{}"]/g, "").slice(0, 80) || "unknown";
        return { ...s, trend: t, errorType };
      })
      .filter((s) => !hideLow || s.count >= 1)
      .filter((s) => !risingOnly || s.trend === "Increasing");

    if (!rows.length) {
      els.signatureRows.innerHTML = "<tr><td colspan='6'>No signatures in current window</td></tr>";
      return;
    }
    rows.forEach((r) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${r.id}</td>
        <td>${r.errorType}</td>
        <td>${r.count}</td>
        <td>${r.firstSeen.replace("T", " ").slice(0, 19)}Z</td>
        <td>${r.lastSeen.replace("T", " ").slice(0, 19)}Z</td>
        <td>${r.trend}</td>
      `;
      els.signatureRows.appendChild(tr);
      r.lastCount = r.count;
    });
  }

  function renderCoverage(data) {
    const missing = data.analysis?.missing_observability || [];
    const dsErrors = data.context?.datasource_errors || {};
    const missingMetrics = missing.filter((x) => x.includes("metric") || x.includes("pool") || x.includes("kafka")).length;
    const missingTraces = missing.filter((x) => x.includes("trace")).length;
    const missingLogs = missing.filter((x) => x.includes("log")).length;
    const score = Math.max(0, 100 - (missing.length * 8) - (Object.keys(dsErrors).length * 6));
    els.coverageScore.textContent = `${score}%`;
    els.missingMetrics.textContent = String(missingMetrics);
    els.missingTraces.textContent = String(missingTraces);
    els.missingLogs.textContent = String(missingLogs);
    els.gapsList.innerHTML = "";
    (missing.length ? missing : ["No major instrumentation gaps detected"]).forEach((g) => {
      const li = document.createElement("li");
      li.textContent = g;
      els.gapsList.appendChild(li);
    });
    els.datasourceErrors.textContent = JSON.stringify(dsErrors, null, 2);
  }

  function recordAudit(action, approved) {
    const entry = {
      action,
      approved,
      role: state.role,
      ts: new Date().toISOString(),
    };
    state.audit.unshift(entry);
    state.audit = state.audit.slice(0, 20);
    if (approved) pushTimeline(`Mitigation: ${action}`, "action");
    renderAudit();
  }

  function renderAudit() {
    els.auditTrail.innerHTML = "";
    if (!state.audit.length) {
      els.auditTrail.innerHTML = "<li>No actions executed</li>";
      return;
    }
    state.audit.forEach((a) => {
      const li = document.createElement("li");
      li.textContent = `${a.ts.replace("T", " ").slice(0, 19)}Z | ${a.role} | ${a.action} | ${a.approved ? "approved" : "cancelled"}`;
      els.auditTrail.appendChild(li);
    });
  }

  function enforceRbac() {
    const role = state.role;
    els.actionCenter.querySelectorAll("button").forEach((btn) => {
      const action = btn.dataset.action;
      const allowed = role === "Admin" || (role === "Operator" && action !== "rollback_argocd" && action !== "silence_alert");
      btn.disabled = !allowed;
    });
  }

  function setView(view) {
    state.activeView = view;
    els.viewToggle.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
    els.telemetrySection.classList.toggle("hidden", view === "raw");
    els.aiSection.classList.toggle("hidden", view === "telemetry");
    els.rawSection.classList.toggle("hidden", view !== "raw");
  }

  function updateWhyWarningTable(data) {
    const components = data.context?.components || [];
    const ds = data.context?.datasource_errors || {};
    const missing = data.analysis?.missing_observability || [];
    const rows = components.map((c) => ({
      service: c.service,
      status: c.status,
      reason: (c.reasons || []).join("; ") || "-",
      ds: Object.entries(ds).filter(([k]) => k.startsWith(`${c.service}:`)).map(([, v]) => String(v).slice(0, 70)).join(" | ") || "-",
      missing: missing.slice(0, 3).join("; ") || "-",
    }));
    els.whyWarningRows.innerHTML = "";
    if (!rows.length) {
      els.whyWarningRows.innerHTML = "<tr><td colspan='5'>No impacted services</td></tr>";
      return rows;
    }
    rows.forEach((r) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${r.service}</td>
        <td>${r.status}</td>
        <td>${r.reason}</td>
        <td>${r.ds}</td>
        <td>${r.missing}</td>
      `;
      els.whyWarningRows.appendChild(tr);
    });
    return rows;
  }

  function renderRaw(data) {
    const summary = {
      component_summary: data.context?.component_summary || {},
      why_warning: updateWhyWarningTable(data),
      full: data,
    };
    els.rawJson.textContent = JSON.stringify(summary, null, 2);
  }

  async function refresh() {
    setLiveStatus("loading...", "warn");
    const namespace = (els.namespace.value || "dev").trim();
    const service = (els.service.value || "all").trim();
    const severity = (els.severity.value || "warning").trim();
    try {
      const data = await fetchReasoning(namespace, service, severity);
      state.lastRaw = data;

      renderIncidentHeader(data);
      renderAiPanels(data);
      updateSignatureHistory(data.analysis || {});
      renderSignatureTable();
      renderCoverage(data);
      updateWhyWarningTable(data);
      renderRaw(data);

      const components = data.context?.components || [];
      await hydrateServiceTelemetry(components, namespace, severity);
      renderTelemetryCards(components);

      if ((data.context?.metrics?.anomalies || []).length) pushTimeline("Metric anomaly start", "telemetry");
      if ((data.context?.logs?.count || 0) > 10) pushTimeline("Log spike detected", "logs");
      if (data.context?.deployment?.deployment_changed_last_10m) pushTimeline("Deployment event", "deploy");
      pushTimeline("AI inference trigger", "ai");
      renderTimeline();
      setLiveStatus("live", "ok");
    } catch (e) {
      setLiveStatus(`error: ${e}`, "err");
    }
  }

  function restartAutoRefresh() {
    if (refreshTimer) clearInterval(refreshTimer);
    const sec = Math.max(5, Number(els.interval.value || 20));
    refreshTimer = setInterval(refresh, sec * 1000);
  }

  function bindEvents() {
    els.refreshBtn.addEventListener("click", refresh);
    els.interval.addEventListener("change", restartAutoRefresh);
    els.roleSelect.addEventListener("change", () => {
      state.role = els.roleSelect.value;
      enforceRbac();
    });
    els.risingOnly.addEventListener("change", renderSignatureTable);
    els.hideLowFreq.addEventListener("change", renderSignatureTable);
    els.viewToggle.addEventListener("click", (e) => {
      if (e.target.tagName === "BUTTON") setView(e.target.dataset.view);
    });
    els.actionCenter.addEventListener("click", (e) => {
      if (e.target.tagName !== "BUTTON") return;
      if (e.target.disabled) return;
      const action = e.target.dataset.action;
      const ok = window.confirm(`Confirm action: ${action.replaceAll("_", " ")} ?`);
      recordAudit(action, ok);
    });
  }

  function boot() {
    els.incidentStart.textContent = fmtDate(state.incidentStart);
    bindEvents();
    enforceRbac();
    setView("ai");
    restartAutoRefresh();
    refresh();
    durationTimer = setInterval(renderDuration, 1000);
    renderDuration();
  }

  window.addEventListener("beforeunload", () => {
    if (refreshTimer) clearInterval(refreshTimer);
    if (durationTimer) clearInterval(durationTimer);
  });

  boot();
})();
