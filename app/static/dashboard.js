/* global Chart */
(function () {
  const syncState = { crosshairX: null };

  const deployMarkerPlugin = {
    id: "deployMarkerPlugin",
    afterDraw(chart, args, options) {
      const { ctx, chartArea, scales } = chart;
      if (!chartArea) return;
      const x = scales.x;
      const yRight = scales.y1 || scales.y;
      const yLeft = scales.y;
      const labels = chart.data.labels || [];
      const deploy = options.deploy || [];
      const anomaly = options.anomaly || [];
      const errThreshold = options.errThreshold || 5;

      ctx.save();
      const yT = yRight.getPixelForValue(errThreshold);
      ctx.strokeStyle = "rgba(245,158,11,0.75)";
      ctx.lineWidth = 1;
      ctx.setLineDash([5, 4]);
      ctx.beginPath();
      ctx.moveTo(chartArea.left, yT);
      ctx.lineTo(chartArea.right, yT);
      ctx.stroke();
      ctx.setLineDash([]);

      labels.forEach((_, i) => {
        const px = x.getPixelForValue(i);
        if (deploy[i]) {
          ctx.strokeStyle = "rgba(34,197,94,0.75)";
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.moveTo(px, chartArea.top);
          ctx.lineTo(px, chartArea.bottom);
          ctx.stroke();
        }
        if (anomaly[i]) {
          ctx.strokeStyle = "rgba(239,68,68,0.85)";
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.moveTo(px, chartArea.top);
          ctx.lineTo(px, chartArea.bottom);
          ctx.stroke();
          const py = yLeft.getPixelForValue(chart.data.datasets[0].data[i] || 0);
          ctx.fillStyle = "rgba(239,68,68,0.9)";
          ctx.beginPath();
          ctx.arc(px, py, 3, 0, Math.PI * 2);
          ctx.fill();
        }
      });
      ctx.restore();
    }
  };

  const crosshairPlugin = {
    id: "crosshairPlugin",
    afterDraw(chart) {
      if (!Number.isFinite(syncState.crosshairX)) return;
      const { chartArea, scales, ctx } = chart;
      if (!chartArea || !scales.x) return;
      const px = scales.x.getPixelForValue(syncState.crosshairX);
      if (px < chartArea.left || px > chartArea.right) return;
      ctx.save();
      ctx.strokeStyle = "rgba(147,197,253,0.75)";
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 3]);
      ctx.beginPath();
      ctx.moveTo(px, chartArea.top);
      ctx.lineTo(px, chartArea.bottom);
      ctx.stroke();
      ctx.restore();
    }
  };

  if (window.ChartZoom) Chart.register(window.ChartZoom);
  Chart.register(deployMarkerPlugin, crosshairPlugin);
  Chart.defaults.font.family = "Segoe UI, Arial, sans-serif";
  Chart.defaults.color = "#5b6b82";

  const state = {
    incidentId: `INC-${Math.floor(Date.now() / 1000).toString().slice(-6)}`,
    incidentStart: new Date(),
    slaMinutes: 60,
    role: "Viewer",
    timeline: [],
    audit: [],
    charts: {},
    serviceHistory: {},
    signatures: {},
    selectedSignature: null,
    lastData: null,
    errorTrend: { ts: [], value: [] },
    errorChart: null,
    chartRegistry: new Map(),
    zoomWindow: { min: null, max: null },
    mapView: { scale: 1, tx: 0, ty: 0, dragging: false, dragStartX: 0, dragStartY: 0, focusService: null },
    fullscreenPanel: null,
  };

  const el = {
    incidentHeader: document.getElementById("incidentHeader"),
    severityStrip: document.getElementById("severityStrip"),
    incidentId: document.getElementById("incidentId"),
    incidentStatus: document.getElementById("incidentStatus"),
    incidentSeverity: document.getElementById("incidentSeverity"),
    incidentStart: document.getElementById("incidentStart"),
    incidentDuration: document.getElementById("incidentDuration"),
    incidentOwner: document.getElementById("incidentOwner"),
    incidentSla: document.getElementById("incidentSla"),
    incidentRisk: document.getElementById("incidentRisk"),
    incidentBudget: document.getElementById("incidentBudget"),
    incidentImpact: document.getElementById("incidentImpact"),
    affectedCount: document.getElementById("affectedCount"),
    slaProgressBar: document.getElementById("slaProgressBar"),
    namespace: document.getElementById("namespace"),
    service: document.getElementById("service"),
    severity: document.getElementById("severity"),
    timeWindow: document.getElementById("timeWindow"),
    customWindowWrap: document.getElementById("customWindowWrap"),
    customWindow: document.getElementById("customWindow"),
    interval: document.getElementById("interval"),
    refreshBtn: document.getElementById("refreshBtn"),
    rawToggleBtn: document.getElementById("rawToggleBtn"),
    roleSelect: document.getElementById("roleSelect"),
    viewToggle: document.getElementById("viewToggle"),
    quickNav: document.getElementById("quickNav"),
    aiTabs: document.getElementById("aiTabs"),
    telemetrySection: document.getElementById("telemetrySection"),
    aiSection: document.getElementById("aiSection"),
    rawSection: document.getElementById("rawSection"),
    errorsSection: document.getElementById("errorsSection"),
    coverageSection: document.getElementById("coverageSection"),
    telemetryGrid: document.getElementById("telemetryGrid"),
    errorTrendArrow: document.getElementById("errorTrendArrow"),
    errorTrendLabel: document.getElementById("errorTrendLabel"),
    errorTrendChart: document.getElementById("errorTrendChart"),
    recentChanges: document.getElementById("recentChanges"),
    liveStatus: document.getElementById("liveStatus"),
    rootCauseSummary: document.getElementById("rootCauseSummary"),
    incidentSummaryText: document.getElementById("incidentSummaryText"),
    rootCauseHypothesisText: document.getElementById("rootCauseHypothesisText"),
    metricSummarySignals: document.getElementById("metricSummarySignals"),
    confidence: document.getElementById("confidence"),
    riskWindow: document.getElementById("riskWindow"),
    confidenceBreakdown: document.getElementById("confidenceBreakdown"),
    correlatedSignals: document.getElementById("correlatedSignals"),
    suggestedActions: document.getElementById("suggestedActions"),
    serviceBadges: document.getElementById("serviceBadges"),
    humanSummary: document.getElementById("humanSummary"),
    reasoningJson: document.getElementById("reasoningJson"),
    aiJson: document.getElementById("aiJson"),
    signatureRows: document.getElementById("signatureRows"),
    risingOnly: document.getElementById("risingOnly"),
    hideLowFreq: document.getElementById("hideLowFreq"),
    whyWarningRows: document.getElementById("whyWarningRows"),
    timeline: document.getElementById("timeline"),
    coverageScore: document.getElementById("coverageScore"),
    coverageBarFill: document.getElementById("coverageBarFill"),
    missingMetrics: document.getElementById("missingMetrics"),
    missingTraces: document.getElementById("missingTraces"),
    missingLogs: document.getElementById("missingLogs"),
    gapsList: document.getElementById("gapsList"),
    datasourceErrors: document.getElementById("datasourceErrors"),
    genTaskBtn: document.getElementById("genTaskBtn"),
    rawJson: document.getElementById("rawJson"),
    signatureModal: document.getElementById("signatureModal"),
    modalTitle: document.getElementById("modalTitle"),
    modalBody: document.getElementById("modalBody"),
    closeModalBtn: document.getElementById("closeModalBtn"),
    knownIssueBtn: document.getElementById("knownIssueBtn"),
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
  function severityClass(v) {
    const x = String(v || "").toLowerCase();
    if (x.includes("critical")) return "critical";
    if (x.includes("high")) return "critical";
    if (x.includes("warning") || x.includes("medium")) return "warning";
    if (x.includes("info")) return "info";
    return "healthy";
  }
  function setLiveStatus(text, level) {
    el.liveStatus.textContent = text;
    el.liveStatus.style.color = level === "err" ? "var(--crit)" : level === "warn" ? "var(--warn)" : "var(--muted)";
  }
  function clamp(n, min, max) {
    return Math.max(min, Math.min(max, n));
  }

  function applyZoomToAll(sourceChart) {
    const xScale = sourceChart?.scales?.x;
    if (!xScale) return;
    state.zoomWindow.min = xScale.min;
    state.zoomWindow.max = xScale.max;
    state.chartRegistry.forEach((chart) => {
      if (chart === sourceChart) return;
      chart.options.scales.x.min = state.zoomWindow.min;
      chart.options.scales.x.max = state.zoomWindow.max;
      chart.update("none");
    });
  }

  function resetZoomAll() {
    state.zoomWindow.min = null;
    state.zoomWindow.max = null;
    state.chartRegistry.forEach((chart) => {
      chart.options.scales.x.min = undefined;
      chart.options.scales.x.max = undefined;
      if (typeof chart.resetZoom === "function") chart.resetZoom();
      chart.update("none");
    });
  }

  function initPanelWrappers() {
    document.querySelectorAll(".panel-wrapper").forEach((panel) => {
      const panelId = panel.dataset.panelId || panel.id || `panel-${Math.random().toString(36).slice(2, 6)}`;
      panel.dataset.panelId = panelId;
      if (panel.querySelector(".panel-header-controls")) return;
      const controls = document.createElement("div");
      controls.className = "panel-header-controls";
      controls.innerHTML = `
        <button type="button" data-action="reset" data-panel="${panelId}">Reset</button>
        <button type="button" data-action="fullscreen" data-panel="${panelId}">Fullscreen</button>
      `;
      panel.appendChild(controls);
    });

    document.body.addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-action][data-panel]");
      if (!btn) return;
      if (btn.dataset.action === "fullscreen") {
        toggleFullscreen(btn.dataset.panel);
      } else if (btn.dataset.action === "reset") {
        if (btn.dataset.panel === "telemetry") resetZoomAll();
      }
    });

    window.addEventListener("keydown", (e) => {
      if (e.key === "Escape") exitFullscreen();
    });
  }

  function toggleFullscreen(panelId) {
    const panel = document.querySelector(`.panel-wrapper[data-panel-id="${panelId}"]`);
    if (!panel) return;
    if (state.fullscreenPanel === panelId) {
      exitFullscreen();
      return;
    }
    document.body.classList.add("fullscreen-mode");
    document.querySelectorAll(".panel-fullscreen").forEach((p) => p.classList.remove("panel-fullscreen"));
    panel.classList.add("panel-fullscreen");
    state.fullscreenPanel = panelId;
  }

  function exitFullscreen() {
    document.body.classList.remove("fullscreen-mode");
    document.querySelectorAll(".panel-fullscreen").forEach((p) => p.classList.remove("panel-fullscreen"));
    state.fullscreenPanel = null;
  }

  async function fetchReasoning(namespace, service, severity) {
    let tw = (el.timeWindow.value || "30m").trim();
    if (tw === "custom") tw = `${Math.max(5, Math.min(360, Number(el.customWindow.value || 30)))}m`;
    const qs = new URLSearchParams({ namespace, service, severity, time_window: tw }).toString();
    const res = await fetch(`/api/reasoning/live?${qs}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  function ensureHistory(service) {
    if (!state.serviceHistory[service]) {
      state.serviceHistory[service] = { ts: [], rps: [], err: [], p95: [], p99: [], cpu: [], mem: [], db: [], kafka: [], restarts: [], anomaly: [], deploy: [] };
    }
    return state.serviceHistory[service];
  }
  function capHistory(h) {
    Object.keys(h).forEach((k) => {
      if (Array.isArray(h[k]) && h[k].length > 90) h[k] = h[k].slice(-90);
    });
  }
  function hasMetricSignal(metrics) {
    if (!metrics || typeof metrics !== "object") return false;
    const keys = [
      "request_rate_rps_5m",
      "error_rate_5xx_5m",
      "latency_p95_s_5m",
      "latency_p99_s_5m",
      "cpu_usage_cores_5m",
      "memory_usage_bytes",
      "db_connection_pool_usage_5m",
      "kafka_consumer_lag",
    ];
    return keys.some((k) => Number(metrics[k] || 0) > 0);
  }
  function pushTelemetryPoint(service, context) {
    const hist = ensureHistory(service);
    const m = context.metrics || {};
    const d = context.deployment || {};
    hist.ts.push(new Date().toLocaleTimeString());
    hist.rps.push(m.request_rate_rps_5m || 0);
    hist.err.push((m.error_rate_5xx_5m || 0) * 100);
    hist.p95.push((m.latency_p95_s_5m || 0) * 1000);
    hist.p99.push((m.latency_p99_s_5m || 0) * 1000);
    hist.cpu.push((m.cpu_usage_cores_5m || 0) * 100);
    hist.mem.push((m.memory_usage_bytes || 0) / (1024 * 1024));
    hist.db.push((m.db_connection_pool_usage_5m || 0) * 100);
    hist.kafka.push(m.kafka_consumer_lag || 0);
    hist.restarts.push(m.pod_restarts_10m || 0);
    hist.anomaly.push((m.anomalies || []).length > 0 ? 1 : 0);
    hist.deploy.push(d.deployment_changed_last_10m ? 1 : 0);
    capHistory(hist);
  }

  async function hydrateServiceTelemetry(components, _namespace, _severity, fallbackContext, componentMetrics) {
    (components || []).forEach((component) => {
      const svc = component.service;
      const metrics = componentMetrics?.[svc] || {};
      if (hasMetricSignal(metrics)) {
        pushTelemetryPoint(svc, { metrics, deployment: fallbackContext?.deployment || {}, kubernetes: fallbackContext?.kubernetes || {} });
      } else {
        pushTelemetryPoint(svc, { metrics: {}, deployment: fallbackContext?.deployment || {}, kubernetes: fallbackContext?.kubernetes || {} });
      }
    });
  }

  function buildServiceStats(serviceName, history, componentMetrics) {
    const m = componentMetrics?.[serviceName] || {};
    const h = history || {};
    const rps = Number(m.request_rate_rps_5m ?? h.rps?.at?.(-1) ?? 0) || 0;
    const err = Number((m.error_rate_5xx_5m ?? 0) * 100 || h.err?.at?.(-1) || 0) || 0;
    const p95 = Number((m.latency_p95_s_5m ?? 0) * 1000 || h.p95?.at?.(-1) || 0) || 0;
    const cpu = Number((m.cpu_usage_cores_5m ?? 0) * 100 || h.cpu?.at?.(-1) || 0) || 0;
    const mem = Number((m.memory_usage_bytes ?? 0) / (1024 * 1024) || h.mem?.at?.(-1) || 0) || 0;
    const restarts = Number(m.pod_restarts_10m ?? h.restarts?.at?.(-1) ?? 0) || 0;
    return { rps, err, p95, cpu, mem, restarts };
  }

  function chartConfig(hist) {
    return {
      type: "line",
      data: {
        labels: hist.ts,
        datasets: [
          { label: "p95 (ms)", data: hist.p95, yAxisID: "y", borderColor: "#56A64B", borderWidth: 2, pointRadius: 0, tension: 0.25 },
          { label: "p99 (ms)", data: hist.p99, yAxisID: "y", borderColor: "#9BCB93", borderWidth: 2, pointRadius: 0, tension: 0.25 },
          { label: "5xx (%)", data: hist.err, yAxisID: "y1", borderColor: "#F28B4B", borderWidth: 2, pointRadius: 0, tension: 0.25, borderDash: [6, 4] },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: "index", intersect: false },
        onHover(_evt, elements, chart) {
          if (!elements || !elements.length) return;
          syncState.crosshairX = elements[0].index;
          state.chartRegistry.forEach((c) => {
            if (c !== chart) c.draw();
          });
        },
        plugins: {
          legend: { labels: { color: "#5b6b82", boxWidth: 10 } },
          tooltip: {
            backgroundColor: "#ffffff",
            borderColor: "#d7dee9",
            borderWidth: 1,
            titleColor: "#1f2937",
            bodyColor: "#1f2937",
            displayColors: true,
          },
          deployMarkerPlugin: { deploy: hist.deploy, anomaly: hist.anomaly, errThreshold: 5 },
          zoom: {
            pan: { enabled: true, mode: "x" },
            zoom: {
              wheel: { enabled: true },
              pinch: { enabled: true },
              drag: { enabled: true, backgroundColor: "rgba(59,130,246,0.15)", borderColor: "rgba(59,130,246,0.45)", borderWidth: 1 },
              mode: "x",
            },
            onZoomComplete(ctx) {
              applyZoomToAll(ctx.chart);
            },
            onPanComplete(ctx) {
              applyZoomToAll(ctx.chart);
            }
          }
        },
        scales: {
          x: {
            min: state.zoomWindow.min ?? undefined,
            max: state.zoomWindow.max ?? undefined,
            ticks: { color: "#7a8799", maxTicksLimit: 8 },
            grid: { color: "rgba(130,145,166,0.15)" }
          },
          y: { ticks: { color: "#7a8799" }, grid: { color: "rgba(130,145,166,0.15)" } },
          y1: { position: "right", ticks: { color: "#d5753b" }, grid: { drawOnChartArea: false } },
        },
      },
    };
  }

  function renderTelemetryCards(components) {
    el.telemetryGrid.innerHTML = "";
    state.chartRegistry.forEach((chart) => chart.destroy());
    state.chartRegistry.clear();
    (components || []).forEach((component) => {
      const svc = component.service;
      const hist = ensureHistory(svc);
      const cls = severityClass(component.status);
      const card = document.createElement("div");
      card.className = `telemetry-card sev-${cls}`;
      card.innerHTML = `
        <h3>${svc}</h3>
        <div class="telemetry-meta">
          <span class="pill ${component.status}">${String(component.status).toUpperCase()}</span>
          <span class="pill">RPS ${Number(hist.rps.at(-1) || 0).toFixed(2)}</span>
          <span class="pill">5xx ${Number(hist.err.at(-1) || 0).toFixed(2)}%</span>
          <span class="pill">p95 ${Math.round(hist.p95.at(-1) || 0)}ms</span>
          <span class="pill">p99 ${Math.round(hist.p99.at(-1) || 0)}ms</span>
          <span class="pill">CPU ${Math.round(hist.cpu.at(-1) || 0)}%</span>
          <span class="pill">MEM ${Math.round(hist.mem.at(-1) || 0)}MB</span>
          <span class="pill">DB ${Math.round(hist.db.at(-1) || 0)}%</span>
          <span class="pill">Kafka ${Math.round(hist.kafka.at(-1) || 0)}</span>
        </div>
        <div class="telemetry-actions">
          <button class="link-btn" data-open="logs" data-service="${svc}">View Logs</button>
          <button class="link-btn" data-open="traces" data-service="${svc}">View Traces</button>
        </div>
        <div class="stacked-charts">
          <div class="stack-chart"><canvas id="chart-main-${svc}"></canvas></div>
          <div class="stack-chart"><canvas id="chart-resource-${svc}"></canvas></div>
        </div>
      `;
      el.telemetryGrid.appendChild(card);
      const cvMain = card.querySelector(`#chart-main-${CSS.escape(svc)}`);
      const cvResource = card.querySelector(`#chart-resource-${CSS.escape(svc)}`);
      const mainChart = new Chart(cvMain, chartConfig(hist));
      const resourceHist = { ...hist, p95: hist.cpu, p99: hist.mem, err: hist.db };
      const resourceChart = new Chart(cvResource, chartConfig(resourceHist));
      state.chartRegistry.set(`main-${svc}`, mainChart);
      state.chartRegistry.set(`resource-${svc}`, resourceChart);
      cvMain.addEventListener("dblclick", resetZoomAll);
      cvResource.addEventListener("dblclick", resetZoomAll);
    });
  }

  function renderHeader(data) {
    const sev = severityClass(el.severity.value);
    const riskWindow = data.analysis?.risk_forecast?.predicted_breach_window || "low_risk";
    const riskPct = String(riskWindow).includes("1h") ? 85 : String(riskWindow).includes("24h") ? 62 : 18;
    const burn24 = data.context?.slo?.error_budget_burn_rate_24h || 0;
    const budget = Math.max(0, Math.round(100 - burn24 * 10));
    el.incidentId.textContent = state.incidentId;
    el.incidentStatus.textContent = riskPct > 80 ? "CRITICAL" : riskPct > 45 ? "INVESTIGATING" : "MITIGATING";
    el.incidentSeverity.textContent = String(el.severity.value || "medium").toUpperCase();
    el.incidentStart.textContent = fmtDate(state.incidentStart);
    el.incidentOwner.textContent = state.role === "Viewer" ? "oncall-sre" : `${state.role.toLowerCase()}-operator`;
    el.incidentRisk.textContent = `${riskPct}%`;
    el.incidentBudget.textContent = `${budget}%`;
    el.incidentImpact.textContent = data.analysis?.impact_level || "Low";
    el.affectedCount.textContent = String(data.context?.component_summary?.total || 0);
    el.incidentHeader.className = `incident-header sev-${sev}`;
    const color = sev === "critical" ? "var(--crit)" : sev === "warning" ? "var(--warn)" : sev === "healthy" ? "var(--ok)" : "var(--info)";
    el.severityStrip.style.background = color;
  }

  function renderDuration() {
    const elapsed = new Date() - state.incidentStart;
    const left = Math.max(0, state.slaMinutes * 60000 - elapsed);
    el.incidentDuration.textContent = fmtDuration(elapsed);
    el.incidentSla.textContent = fmtDuration(left);
    const pct = Math.max(0, Math.min(100, (left / (state.slaMinutes * 60000)) * 100));
    el.slaProgressBar.style.width = `${pct}%`;
  }

  function deriveConfidenceBreakdown(data) {
    const missing = data.analysis?.missing_observability || [];
    const ds = data.context?.datasource_errors || {};
    return {
      metric: Math.max(20, 58 - missing.length * 4),
      logs: ds.loki || Object.keys(ds).some((k) => k.includes(":loki")) ? 25 : 70,
      trace: ds.jaeger ? 25 : 65,
      historical: Math.max(20, 72 - missing.length * 5),
    };
  }

  function renderAi(data) {
    const a = data.analysis || {};
    const c = data.context || {};
    const selectedService = (el.service?.value || c.alert?.service || "all").trim();
    const focusService = selectedService === "all" ? (c.components?.[0]?.service || "all") : selectedService;
    const cm = c.component_metrics?.[focusService] || {};
    const p95ms = Math.round(Number(cm.latency_p95_s_5m || 0) * 1000);
    const errPct = Number(cm.error_rate_5xx_5m || 0) * 100;
    const cpuPct = Number(cm.cpu_usage_cores_5m || 0) * 100;
    const memMb = Number(cm.memory_usage_bytes || 0) / (1024 * 1024);

    if (el.rootCauseSummary) el.rootCauseSummary.textContent = a.probable_root_cause || "-";
    if (el.confidence) el.confidence.textContent = a.confidence_score || "-";
    if (el.riskWindow) el.riskWindow.textContent = a.risk_forecast?.predicted_breach_window || "-";
    if (el.humanSummary) el.humanSummary.textContent = a.human_summary || "-";
    if (el.reasoningJson) el.reasoningJson.textContent = JSON.stringify({ causal_chain: a.causal_chain || [], corrective_actions: a.corrective_actions || [], preventive_hardening: a.preventive_hardening || [] }, null, 2);
    if (el.aiJson) el.aiJson.textContent = JSON.stringify({ analysis: a, component_summary: c.component_summary || {} }, null, 2);
    if (el.incidentSummaryText) {
      el.incidentSummaryText.textContent = `Incident ${state.incidentId} | Severity ${String(el.severity?.value || "warning").toUpperCase()} | Service ${focusService}.`;
    }
    if (el.rootCauseHypothesisText) {
      el.rootCauseHypothesisText.textContent = a.human_summary || a.probable_root_cause || "No dominant hypothesis generated.";
    }
    if (el.metricSummarySignals) {
      const metricLines = [
        `p95 latency: ${p95ms}ms ${p95ms > 750 ? "(elevated)" : "(stable)"}`,
        `5xx error rate: ${errPct.toFixed(2)}% ${errPct > 5 ? "(elevated)" : "(stable)"}`,
        `CPU usage: ${Math.round(cpuPct)}% ${(cpuPct > 80) ? "(high)" : "(normal)"}`,
        `Memory usage: ${Math.round(memMb)}MB ${(memMb > 1024) ? "(high)" : "(normal)"}`,
      ];
      el.metricSummarySignals.innerHTML = "";
      metricLines.forEach((line) => {
        const li = document.createElement("li");
        li.textContent = line;
        el.metricSummarySignals.appendChild(li);
      });
    }

    const conf = deriveConfidenceBreakdown(data);
    if (el.confidenceBreakdown) el.confidenceBreakdown.innerHTML = `
      <span class="chip">Metric ${conf.metric}%</span>
      <span class="chip">Logs ${conf.logs}%</span>
      <span class="chip">Trace ${conf.trace}%</span>
      <span class="chip">Historical ${conf.historical}%</span>
    `;
    if (el.correlatedSignals) el.correlatedSignals.innerHTML = "";
    (a.causal_chain || ["No strong multi-signal causal chain detected"]).forEach((line) => {
      if (!el.correlatedSignals) return;
      const li = document.createElement("li");
      li.textContent = line;
      el.correlatedSignals.appendChild(li);
    });
    if (el.suggestedActions) {
      const steps = [...(a.corrective_actions || []), ...(a.recommended_remediation ? [a.recommended_remediation] : [])].slice(0, 4);
      el.suggestedActions.innerHTML = "";
      (steps.length ? steps : ["Continue monitoring and validate service dependencies."]).forEach((step) => {
        const li = document.createElement("li");
        li.textContent = step;
        el.suggestedActions.appendChild(li);
      });
    }
  }

  function renderDependencyMap(components, summary, statsByService, clusterWiring) {
    if (!el.dependencyMap) return;
    const wiring = (clusterWiring && Array.isArray(clusterWiring.nodes) && clusterWiring.nodes.length)
      ? clusterWiring
      : { nodes: (components || []).map((c) => ({ id: c.service, kind: "service", status: c.status })), edges: [] };

    const services = (wiring.nodes || []).filter((n) => n.kind === "service" && n.id !== "kubernetes").sort((a, b) => a.id.localeCompare(b.id));
    const pods = (wiring.nodes || []).filter((n) => n.kind === "pod").sort((a, b) => a.id.localeCompare(b.id));
    const podByService = {};
    services.forEach((s) => { podByService[s.id] = []; });
    (wiring.edges || []).forEach((e) => {
      const fromSvc = services.find((s) => s.id === e.from);
      const toPod = pods.find((p) => p.id === e.to);
      if (fromSvc && toPod && !podByService[fromSvc.id].includes(toPod.id)) podByService[fromSvc.id].push(toPod.id);
    });
    pods.forEach((pod) => {
      const owner = services.find((s) => pod.id.includes(s.id.replace("-service", "")) || pod.id.includes(s.id));
      if (owner && !podByService[owner.id].includes(pod.id)) podByService[owner.id].push(pod.id);
    });
    const serviceForPod = {};
    Object.entries(podByService).forEach(([svc, podNames]) => {
      podNames.forEach((p) => { serviceForPod[p] = svc; });
    });

    const containerWidth = Math.max(900, Math.floor(el.dependencyMap?.clientWidth || 900));
    const serviceNodeW = 260;
    const serviceNodeH = 52;
    const podNodeW = 260;
    const podNodeH = 102;
    const colGap = 28;
    const podGap = 14;
    const topPad = 24;
    const bottomPad = 24;
    const leftPad = 24;
    const rightPad = 24;
    const minColWidth = serviceNodeW + colGap;
    const columns = Math.max(1, Math.floor((containerWidth - leftPad - rightPad) / minColWidth));
    const maxPodsInService = Math.max(1, ...services.map((s) => (podByService[s.id] || []).length));
    const perServiceHeight = serviceNodeH + 18 + (maxPodsInService * (podNodeH + podGap));
    const rowGap = 28;
    const serviceRows = Math.max(1, Math.ceil(services.length / columns));
    const width = Math.max(containerWidth, leftPad + rightPad + (Math.min(columns, Math.max(1, services.length)) * minColWidth));
    const height = Math.max(460, topPad + bottomPad + (serviceRows * perServiceHeight) + ((serviceRows - 1) * rowGap));
    const focus = state.mapView.focusService;
    const nodeStatusColor = (status) => status === "critical" ? "#ef4444" : status === "warning" ? "#f59e0b" : "#22c55e";

    if (el.dependencyMap) {
      el.dependencyMap.setAttribute("viewBox", `0 0 ${width} ${height}`);
      el.dependencyMap.setAttribute("preserveAspectRatio", "xMidYMid meet");
    }

    let svg = `
      <defs>
        <marker id="depArrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="strokeWidth">
          <path d="M0,0 L8,4 L0,8 z" fill="#5f7ba3"></path>
        </marker>
      </defs>
      <rect width="${width}" height="${height}" fill="#0b1426"/>
      <g id="depViewport" transform="translate(${state.mapView.tx},${state.mapView.ty}) scale(${state.mapView.scale})">
    `;

    const nodes = [];
    services.forEach((svc, i) => {
      const col = i % columns;
      const row = Math.floor(i / columns);
      const x = leftPad + (col * minColWidth);
      const y = topPad + (row * (perServiceHeight + rowGap));
      const svcStat = statsByService[svc.id] || { p95: 0, err: 0, rps: 0, cpu: 0, mem: 0, restarts: 0 };
      nodes.push({ id: svc.id, kind: "service", x, y, w: serviceNodeW, h: serviceNodeH, status: svc.status || "healthy", metric: svcStat });
      (podByService[svc.id] || []).sort().forEach((podName, pIdx) => {
        const py = y + serviceNodeH + 14 + (pIdx * (podNodeH + podGap));
        const err = Number(svcStat.err || 0);
        const p95 = Number(svcStat.p95 || 0);
        nodes.push({
          id: podName,
          service: svc.id,
          kind: "pod",
          x,
          y: py,
          w: podNodeW,
          h: podNodeH,
          status: err > 5 ? "critical" : (err > 1 ? "warning" : "healthy"),
          metric: {
            cpu: `${Math.round(svcStat.cpu || 0)}%`,
            mem: `${Math.round(svcStat.mem || 0)}MB`,
            restart: `${Math.round(svcStat.restarts || 0)}`,
            err: `${err.toFixed(2)}%`,
            p95: `${Math.round(p95)}ms`,
            anomaly: err > 5 || p95 > 800
          }
        });
      });
    });

    const nodeMap = {};
    nodes.forEach((n) => { nodeMap[n.id] = n; });

    const renderedEdges = new Set();
    (wiring.edges || []).forEach((e) => {
      const from = nodeMap[e.from];
      const to = nodeMap[e.to];
      if (!from || !to) return;
      if (from.kind !== "service" || to.kind !== "pod") return;
      const edgeKey = `${from.id}->${to.id}`;
      if (renderedEdges.has(edgeKey)) return;
      renderedEdges.add(edgeKey);
      const svcKey = from.id || serviceForPod[to.id];
      if (!svcKey || serviceForPod[to.id] !== svcKey) return;
      const met = statsByService[svcKey] || { p95: 0, err: 0, rps: 0, cpu: 0, mem: 0, restarts: 0 };
      const err = Number(met.err || 0);
      const dim = focus && from.id !== focus && to.id !== focus && from.service !== focus && to.service !== focus;
      const color = err > 5 ? "#ef4444" : err > 1 ? "#f59e0b" : "#5f7ba3";
      const dash = err > 5 ? "stroke-dasharray='6 4'" : "";
      const widthLine = clamp(1 + (Number(met.rps || 0) / 10), 1.2, 5);
      const x1 = from.x + from.w / 2;
      const y1 = from.y + from.h;
      const x2 = to.x + to.w / 2;
      const y2 = to.y;
      svg += `
        <g class="${dim ? "dep-focus-dim" : ""}">
          <line class="dep-edge ${err > 5 ? "crit" : (err > 1 ? "warn" : "")}" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${color}" stroke-width="${widthLine}" ${dash} marker-end="url(#depArrow)"/>
          <text x="${(x1 + x2) / 2}" y="${(y1 + y2) / 2 - 6}" fill="#8fa3c4" font-size="9">
            RPS ${Number(met.rps || 0).toFixed(2)} | Err ${err.toFixed(2)}% | Avg ${Math.round(Number(met.p95 || 0))}ms
          </text>
        </g>
      `;
    });

    nodes.forEach((n) => {
      const color = nodeStatusColor(n.status || "healthy");
      const dim = focus && n.id !== focus && n.service !== focus;
      if (n.kind === "service") {
        svg += `
          <g class="dep-node service ${dim ? "dep-focus-dim" : ""}" data-service="${n.id}">
            <rect x="${n.x}" y="${n.y}" width="${n.w}" height="${n.h}" rx="8" ry="8" stroke="${color}" stroke-width="2"/>
            <text x="${n.x + 10}" y="${n.y + 18}">${n.id}</text>
            <text x="${n.x + 10}" y="${n.y + 34}" fill="#93a7c7" font-size="10">p95 ${Math.round(Number(n.metric.p95 || 0))}ms | err ${Number(n.metric.err || 0).toFixed(2)}%</text>
          </g>
        `;
      } else {
        svg += `
          <g class="dep-node pod ${n.metric.anomaly ? "anomaly" : ""} ${dim ? "dep-focus-dim" : ""}" data-service="${n.service}">
            <rect x="${n.x}" y="${n.y}" width="${n.w}" height="${n.h}" rx="8" ry="8" stroke="${color}" stroke-width="1.8"/>
            <text x="${n.x + 8}" y="${n.y + 16}">${n.id}</text>
            <text x="${n.x + 8}" y="${n.y + 36}">CPU ${n.metric.cpu} | Mem ${n.metric.mem}</text>
            <text x="${n.x + 8}" y="${n.y + 56}">Restart ${n.metric.restart} | Err ${n.metric.err}</text>
            <text x="${n.x + 8}" y="${n.y + 76}">P95 ${n.metric.p95}</text>
          </g>
        `;
      }
    });
    svg += "</g>";
    el.dependencyMap.innerHTML = svg;
  }

  function rerenderMap() {
    if (!el.dependencyMap) return;
    const c = state.lastData?.context || {};
    const statsByService = {};
    const componentMetrics = c.component_metrics || {};
    (c.components || []).forEach((svc) => {
      const h = state.serviceHistory[svc.service];
      statsByService[svc.service] = buildServiceStats(svc.service, h, componentMetrics);
    });
    renderDependencyMap(c.components || [], c.component_summary || {}, statsByService, c.cluster_wiring || {});
  }

  function resetMapView() {
    if (!el.dependencyMap) return;
    state.mapView.scale = 1;
    state.mapView.tx = 0;
    state.mapView.ty = 0;
    state.mapView.focusService = null;
    rerenderMap();
  }

  function fitMapView() {
    if (!el.dependencyMap) return;
    const viewport = el.dependencyMap?.querySelector("#depViewport");
    if (!viewport) return;
    const bbox = viewport.getBBox();
    if (!bbox.width || !bbox.height) return;
    const vb = el.dependencyMap.viewBox.baseVal;
    const s = Math.min((vb.width - 20) / bbox.width, (vb.height - 20) / bbox.height);
    state.mapView.scale = clamp(s, 0.6, 1.8);
    state.mapView.tx = (vb.width - bbox.width * state.mapView.scale) / 2 - bbox.x * state.mapView.scale;
    state.mapView.ty = (vb.height - bbox.height * state.mapView.scale) / 2 - bbox.y * state.mapView.scale;
    rerenderMap();
  }

  function bindMapInteractions() {
    if (!el.dependencyMap) return;
    el.dependencyMap.addEventListener("wheel", (ev) => {
      ev.preventDefault();
      state.mapView.scale = clamp(state.mapView.scale * (ev.deltaY < 0 ? 1.12 : 0.9), 0.5, 3.5);
      rerenderMap();
    }, { passive: false });
    el.dependencyMap.addEventListener("pointerdown", (ev) => {
      state.mapView.dragging = true;
      state.mapView.dragStartX = ev.clientX - state.mapView.tx;
      state.mapView.dragStartY = ev.clientY - state.mapView.ty;
      el.dependencyMap.setPointerCapture(ev.pointerId);
    });
    el.dependencyMap.addEventListener("pointermove", (ev) => {
      if (!state.mapView.dragging) return;
      state.mapView.tx = ev.clientX - state.mapView.dragStartX;
      state.mapView.ty = ev.clientY - state.mapView.dragStartY;
      rerenderMap();
    });
    const stopDrag = (ev) => {
      state.mapView.dragging = false;
      if (ev?.pointerId != null) {
        try { el.dependencyMap.releasePointerCapture(ev.pointerId); } catch (_e) {}
      }
    };
    el.dependencyMap.addEventListener("pointerup", stopDrag);
    el.dependencyMap.addEventListener("pointercancel", stopDrag);
    el.dependencyMap.addEventListener("dblclick", () => {
      state.mapView.scale = clamp(state.mapView.scale * 1.2, 0.5, 3.5);
      rerenderMap();
    });
    el.dependencyMap.addEventListener("click", (ev) => {
      const target = ev.target.closest("[data-service]");
      if (!target) return;
      const svc = target.getAttribute("data-service");
      state.mapView.focusService = state.mapView.focusService === svc ? null : svc;
      if (svc) {
        el.service.value = svc;
        refresh();
      } else rerenderMap();
    });
    if (el.mapFitBtn) el.mapFitBtn.addEventListener("click", fitMapView);
    if (el.mapResetBtn) el.mapResetBtn.addEventListener("click", resetMapView);
    if (el.mapFullscreenBtn) {
      el.mapFullscreenBtn.addEventListener("click", async () => {
        const target = el.dependencyMap;
        if (!target) return;
        if (document.fullscreenElement) {
          await document.exitFullscreen();
          return;
        }
        if (typeof target.requestFullscreen === "function") {
          await target.requestFullscreen();
        }
      });
    }
  }

  function updateSignatureHistory(analysis) {
    const list = analysis.error_log_prediction?.repeated_signatures || [];
    const now = new Date().toISOString();
    list.forEach((item) => {
      const raw = String(item.signature || "");
      const id = hashCode(raw);
      const count = Number(item.count || 0);
      if (!state.signatures[id]) {
        state.signatures[id] = { id, raw, count, lastCount: count, firstSeen: now, lastSeen: now };
      } else {
        state.signatures[id].lastSeen = now;
        state.signatures[id].count = count;
      }
    });
  }
  function trend(curr, prev) {
    if (curr > prev) return "Increasing";
    if (curr < prev) return "Decreasing";
    return "Stable";
  }

  function renderSignatures(data) {
    el.signatureRows.innerHTML = "";
    const risingOnly = el.risingOnly.checked;
    const hideLow = el.hideLowFreq.checked;
    const rows = Object.values(state.signatures)
      .map((s) => ({ ...s, growth: trend(s.count, s.lastCount), errorType: s.raw.replace(/[{}"]/g, "").slice(0, 95) || "unknown" }))
      .filter((r) => !hideLow || r.count > 0)
      .filter((r) => !risingOnly || r.growth === "Increasing");

    if (!rows.length) {
      el.signatureRows.innerHTML = "<tr><td colspan='6'>No signatures in current window</td></tr>";
      return;
    }
    rows.forEach((r) => {
      const tr = document.createElement("tr");
      tr.className = `sig-row ${r.growth.toLowerCase()}`;
      tr.dataset.sigId = r.id;
      tr.innerHTML = `
        <td>${r.id}</td>
        <td>${r.errorType}</td>
        <td>${r.count}</td>
        <td>${r.firstSeen.replace("T", " ").slice(0, 19)}Z</td>
        <td>${r.lastSeen.replace("T", " ").slice(0, 19)}Z</td>
        <td>${r.growth}</td>
      `;
      el.signatureRows.appendChild(tr);
      r.lastCount = r.count;
    });

    const dsErr = data.context?.datasource_errors || {};
    const missing = data.analysis?.missing_observability || [];
    const comp = data.context?.components || [];
    el.whyWarningRows.innerHTML = "";
    if (!comp.length) {
      el.whyWarningRows.innerHTML = "<tr><td colspan='5'>No impacted services</td></tr>";
    } else {
      comp.forEach((c) => {
        const err = Object.entries(dsErr).filter(([k]) => k.startsWith(`${c.service}:`)).map(([, v]) => String(v).slice(0, 70)).join(" | ") || "-";
        const tr = document.createElement("tr");
        tr.className = `sig-row ${String(c.status || "healthy").toLowerCase()}`;
        tr.innerHTML = `<td>${c.service}</td><td>${c.status}</td><td>${(c.reasons || []).join("; ") || "-"}</td><td>${err}</td><td>${missing.slice(0, 3).join("; ") || "-"}</td>`;
        el.whyWarningRows.appendChild(tr);
      });
    }
  }

  function renderCoverage(data) {
    const gaps = data.analysis?.missing_observability || [];
    const ds = data.context?.datasource_errors || {};
    const missingMetrics = gaps.filter((g) => g.includes("metric") || g.includes("pool") || g.includes("kafka")).length;
    const missingTraces = gaps.filter((g) => g.includes("trace")).length;
    const missingLogs = gaps.filter((g) => g.includes("log")).length;
    const score = Math.max(0, Math.round(100 - (gaps.length * 8) - (Object.keys(ds).length * 6)));
    el.coverageScore.textContent = `${score}%`;
    el.coverageBarFill.style.width = `${score}%`;
    el.missingMetrics.textContent = String(missingMetrics);
    el.missingTraces.textContent = String(missingTraces);
    el.missingLogs.textContent = String(missingLogs);
    const gapInfo = {
      "kafka_consumer_lag": { why: "Detect backlog growth before consumer outage.", sample: "kafka_consumergroup_lag" },
      "thread_pool_saturation": { why: "Detect request queue pressure and saturation.", sample: "jvm_threads_live_threads / jvm_threads_peak_threads" },
      "db_connection_pool_usage": { why: "Detect connection starvation and timeout risk.", sample: "hikaricp_connections_active / hikaricp_connections_max" },
      "argocd deployment history": { why: "Correlate incidents with recent rollouts.", sample: "argocd_app_sync_total" },
      "cicd pipeline signals": { why: "Correlate build failures with runtime degradation.", sample: "pipeline_run_status" },
    };
    el.gapsList.innerHTML = "";
    (gaps.length ? gaps : ["No major instrumentation gaps detected"]).forEach((g) => {
      let why = "";
      let sample = "";
      Object.keys(gapInfo).forEach((k) => {
        if (String(g).toLowerCase().includes(k.toLowerCase())) {
          why = gapInfo[k].why;
          sample = gapInfo[k].sample;
        }
      });
      const li = document.createElement("li");
      li.textContent = why ? `${g} | Why: ${why} | Sample: ${sample}` : g;
      el.gapsList.appendChild(li);
    });
    el.datasourceErrors.textContent = JSON.stringify(ds, null, 2);
  }

  function renderErrorTrend(globalErrorPct) {
    const now = new Date().toLocaleTimeString();
    state.errorTrend.ts.push(now);
    state.errorTrend.value.push(globalErrorPct || 0);
    if (state.errorTrend.ts.length > 90) {
      state.errorTrend.ts = state.errorTrend.ts.slice(-90);
      state.errorTrend.value = state.errorTrend.value.slice(-90);
    }
    const vals = state.errorTrend.value;
    const n = vals.length;
    const recent = n >= 2 ? vals[n - 1] - vals[n - 2] : 0;
    const arrow = recent > 0.1 ? "UP" : recent < -0.1 ? "DOWN" : "FLAT";
    const label = recent > 0.1 ? "Increasing" : recent < -0.1 ? "Decreasing" : "Stable";
    el.errorTrendArrow.textContent = arrow;
    el.errorTrendLabel.textContent = label;
    if (state.errorChart) state.errorChart.destroy();
    state.errorChart = new Chart(el.errorTrendChart, {
      type: "line",
      data: {
        labels: state.errorTrend.ts,
        datasets: [{ label: "Error %", data: state.errorTrend.value, borderColor: "#56A64B", borderWidth: 2, pointRadius: 0, tension: 0.25 }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: "index", intersect: false },
        onHover(_evt, elements, chart) {
          if (!elements || !elements.length) return;
          syncState.crosshairX = elements[0].index;
          state.chartRegistry.forEach((c) => { if (c !== chart) c.draw(); });
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: "#ffffff",
            borderColor: "#d7dee9",
            borderWidth: 1,
            titleColor: "#1f2937",
            bodyColor: "#1f2937",
          },
          zoom: {
            pan: { enabled: true, mode: "x" },
            zoom: {
              wheel: { enabled: true },
              pinch: { enabled: true },
              drag: { enabled: true, backgroundColor: "rgba(59,130,246,0.15)", borderColor: "rgba(59,130,246,0.45)", borderWidth: 1 },
              mode: "x",
            },
            onZoomComplete(ctx) { applyZoomToAll(ctx.chart); },
            onPanComplete(ctx) { applyZoomToAll(ctx.chart); }
          }
        },
        scales: {
          x: {
            min: state.zoomWindow.min ?? undefined,
            max: state.zoomWindow.max ?? undefined,
            ticks: { color: "#7a8799", maxTicksLimit: 8 },
            grid: { color: "rgba(130,145,166,0.15)" }
          },
          y: { ticks: { color: "#7a8799" }, grid: { color: "rgba(130,145,166,0.15)" } }
        }
      }
    });
    state.chartRegistry.set("error-trend", state.errorChart);
    el.errorTrendChart.addEventListener("dblclick", resetZoomAll);
  }

  function renderRecentChanges(data) {
    const c = data.context || {};
    const k = c.kubernetes || {};
    const d = c.deployment || {};
    const list = [];
    if (d.ai_observer_frontend_changed_last_15m) list.push("AI Observer frontend deployment changed in last 15m.");
    if (d.ai_observer_started_at) {
      const started = new Date(d.ai_observer_started_at);
      if (!Number.isNaN(started.getTime())) {
        const ageMin = Math.max(0, Math.floor((Date.now() - started.getTime()) / 60000));
        list.push(`AI Observer runtime age: ${ageMin}m since last pod start.`);
      }
    }
    if (d.deployment_changed_last_10m) list.push("Deployment change detected in last 10m.");
    if ((k.pod_restarts_10m || 0) > 0) list.push(`Pod restarts: ${k.pod_restarts_10m} in last 10m.`);
    if ((k.crashloop_pods || 0) > 0) list.push(`CrashLoopBackOff pods: ${k.crashloop_pods}.`);
    if ((k.oom_killed_10m || 0) > 0) list.push(`OOMKilled events: ${k.oom_killed_10m}.`);
    if (!list.length) list.push("No major deployment/restart/config change signal in last 15m.");
    el.recentChanges.innerHTML = "";
    list.forEach((x) => {
      const li = document.createElement("li");
      li.textContent = x;
      el.recentChanges.appendChild(li);
    });
  }

  function pushTimeline(label, type) {
    state.timeline.push({ label, type, ts: new Date().toISOString() });
    state.timeline = state.timeline.slice(-20);
    el.timeline.innerHTML = "";
    state.timeline.forEach((e) => {
      const item = document.createElement("div");
      item.className = "event";
      item.innerHTML = `<strong>${e.label}</strong><small>${e.type} - ${e.ts.replace("T", " ").slice(0, 19)}Z</small>`;
      el.timeline.appendChild(item);
    });
  }

  function enforceRbac() {}

  function setMainView(view) {
    el.viewToggle.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
    el.telemetrySection.classList.toggle("hidden", view === "raw");
    el.errorsSection.classList.toggle("hidden", view === "raw");
    el.aiSection.classList.toggle("hidden", view === "telemetry");
    el.coverageSection.classList.toggle("hidden", view === "telemetry");
    el.rawSection.classList.toggle("hidden", view !== "raw");
  }

  function setAiTab(tab) {
    if (!el.aiTabs) return;
    el.aiTabs.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
    const sig = document.getElementById("aiTabSignals");
    const rea = document.getElementById("aiTabReasoning");
    const jsn = document.getElementById("aiTabJson");
    if (sig) sig.classList.toggle("hidden", tab !== "signals");
    if (rea) rea.classList.toggle("hidden", tab !== "reasoning");
    if (jsn) jsn.classList.toggle("hidden", tab !== "json");
  }

  function renderRaw(data) {
    el.rawJson.textContent = JSON.stringify(data, null, 2);
  }

  async function refresh() {
    setLiveStatus("loading...", "warn");
    const namespace = (el.namespace.value || "dev").trim();
    const service = (el.service.value || "all").trim();
    const severity = (el.severity.value || "warning").trim();
    try {
      const data = await fetchReasoning(namespace, service, severity);
      state.lastData = data;
      renderHeader(data);
      updateSignatureHistory(data.analysis || {});
      renderSignatures(data);
      renderCoverage(data);
      renderRaw(data);
      renderRecentChanges(data);

      const components = data.context?.components || [];
      if (el.telemetrySection && el.telemetrySection.offsetParent !== null) {
        await hydrateServiceTelemetry(
          components,
          namespace,
          severity,
          data.context || {},
          data.context?.component_metrics || {}
        );
        renderTelemetryCards(components);
        renderErrorTrend((data.context?.metrics?.error_rate_5xx_5m || 0) * 100);
      } else {
        await hydrateServiceTelemetry(
          components,
          namespace,
          severity,
          data.context || {},
          data.context?.component_metrics || {}
        );
      }
      renderAi(data);

      const metrics = data.context?.metrics || {};
      if ((metrics.anomalies || []).length) pushTimeline("Metric anomaly start", "telemetry");
      if ((data.context?.logs?.count || 0) > 10) pushTimeline("Log spike", "logs");
      if (data.context?.deployment?.deployment_changed_last_10m) pushTimeline("Deployment event", "deploy");
      pushTimeline("AI inference trigger", "ai");
      setLiveStatus("live", "ok");
    } catch (err) {
      setLiveStatus(`error: ${err}`, "err");
    }
  }

  function restartAutoRefresh() {
    if (refreshTimer) clearInterval(refreshTimer);
    const sec = Math.max(5, Number(el.interval.value || 20));
    refreshTimer = setInterval(refresh, sec * 1000);
  }

  function bindEvents() {
    el.refreshBtn.addEventListener("click", refresh);
    el.interval.addEventListener("change", restartAutoRefresh);
    el.roleSelect.addEventListener("change", () => { state.role = el.roleSelect.value; enforceRbac(); });
    el.risingOnly.addEventListener("change", () => renderSignatures(state.lastData || { context: {}, analysis: {} }));
    el.hideLowFreq.addEventListener("change", () => renderSignatures(state.lastData || { context: {}, analysis: {} }));
    el.viewToggle.addEventListener("click", (e) => {
      if (e.target.tagName === "BUTTON") setMainView(e.target.dataset.view);
    });
    if (el.rawToggleBtn) {
      el.rawToggleBtn.addEventListener("click", () => {
        el.rawSection.classList.toggle("hidden");
      });
    }
    el.timeWindow.addEventListener("change", () => {
      el.customWindowWrap.classList.toggle("hidden", el.timeWindow.value !== "custom");
      refresh();
    });
    el.customWindow.addEventListener("change", refresh);
    el.quickNav.addEventListener("click", (e) => {
      if (e.target.tagName !== "BUTTON") return;
      const id = e.target.dataset.target;
      const target = document.getElementById(id);
      if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
      el.quickNav.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b === e.target));
    });
    if (el.aiTabs) {
      el.aiTabs.addEventListener("click", (e) => {
        if (e.target.tagName === "BUTTON") setAiTab(e.target.dataset.tab);
      });
    }
    el.telemetryGrid.addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-open]");
      if (!btn) return;
      const svc = btn.dataset.service;
      const ns = (el.namespace.value || "dev").trim();
      if (btn.dataset.open === "logs") {
        const q = `{namespace="${ns}",pod=~".*${svc}.*"} |= "ERROR"`;
        window.open(`http://127.0.0.1:3100/loki/api/v1/query_range?query=${encodeURIComponent(q)}`, "_blank");
      } else if (btn.dataset.open === "traces") {
        window.open(`http://127.0.0.1:16686/search?service=${encodeURIComponent(svc)}&lookback=1h&limit=20&minDuration=500ms`, "_blank");
      }
    });
    el.signatureRows.addEventListener("click", (e) => {
      const row = e.target.closest("tr.sig-row");
      if (!row) return;
      const sigId = row.dataset.sigId;
      const sig = state.signatures[sigId];
      if (!sig) return;
      state.selectedSignature = sig;
      el.modalTitle.textContent = `Signature Drilldown: ${sig.id}`;
      el.modalBody.textContent = JSON.stringify({
        signature: sig.raw,
        sample_log: sig.raw,
        stack_trace: "stack trace unavailable in current datasource",
        related_traces: "see Jaeger query for service",
        affected_pods: ["product-service", "order-service"]
      }, null, 2);
      el.signatureModal.showModal();
    });
    el.closeModalBtn.addEventListener("click", () => el.signatureModal.close());
    el.knownIssueBtn.addEventListener("click", () => {
      if (!state.selectedSignature) return;
      el.signatureModal.close();
    });
    el.genTaskBtn.addEventListener("click", () => {
      alert("Instrumentation task generated.");
    });
  }

  function boot() {
    el.incidentStart.textContent = fmtDate(state.incidentStart);
    initPanelWrappers();
    bindEvents();
    enforceRbac();
    setMainView("ai");
    setAiTab("signals");
    restartAutoRefresh();
    refresh();
    durationTimer = setInterval(renderDuration, 1000);
    renderDuration();
  }

  window.addEventListener("beforeunload", () => {
    if (refreshTimer) clearInterval(refreshTimer);
    if (durationTimer) clearInterval(durationTimer);
    state.chartRegistry.forEach((chart) => chart.destroy());
    state.chartRegistry.clear();
  });

  boot();
})();

