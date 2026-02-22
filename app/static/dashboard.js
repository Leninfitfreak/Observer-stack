/* global Chart */
(function () {
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

  Chart.register(deployMarkerPlugin);
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
    confidence: document.getElementById("confidence"),
    riskWindow: document.getElementById("riskWindow"),
    confidenceBreakdown: document.getElementById("confidenceBreakdown"),
    correlatedSignals: document.getElementById("correlatedSignals"),
    serviceBadges: document.getElementById("serviceBadges"),
    dependencyMap: document.getElementById("dependencyMap"),
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
      state.serviceHistory[service] = { ts: [], rps: [], err: [], p95: [], p99: [], cpu: [], mem: [], db: [], kafka: [], anomaly: [], deploy: [] };
    }
    return state.serviceHistory[service];
  }
  function capHistory(h) {
    Object.keys(h).forEach((k) => {
      if (Array.isArray(h[k]) && h[k].length > 90) h[k] = h[k].slice(-90);
    });
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
    hist.anomaly.push((m.anomalies || []).length > 0 ? 1 : 0);
    hist.deploy.push(d.deployment_changed_last_10m ? 1 : 0);
    capHistory(hist);
  }

  async function hydrateServiceTelemetry(components, namespace, severity) {
    const jobs = (components || []).map(async (component) => {
      const svc = component.service;
      try {
        const data = await fetchReasoning(namespace, svc, severity);
        pushTelemetryPoint(svc, data.context || {});
      } catch (_e) {
        const hist = ensureHistory(svc);
        hist.ts.push(new Date().toLocaleTimeString());
        ["rps", "err", "p95", "p99", "cpu", "mem", "db", "kafka", "anomaly", "deploy"].forEach((k) => hist[k].push(0));
        capHistory(hist);
      }
    });
    await Promise.all(jobs);
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
        interaction: { mode: "index", intersect: false },
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
        },
        scales: {
          x: { ticks: { color: "#7a8799", maxTicksLimit: 8 }, grid: { color: "rgba(130,145,166,0.15)" } },
          y: { ticks: { color: "#7a8799" }, grid: { color: "rgba(130,145,166,0.15)" } },
          y1: { position: "right", ticks: { color: "#d5753b" }, grid: { drawOnChartArea: false } },
        },
      },
    };
  }

  function renderTelemetryCards(components) {
    el.telemetryGrid.innerHTML = "";
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
        <div class="chart-wrap"><canvas id="chart-${svc}"></canvas></div>
      `;
      el.telemetryGrid.appendChild(card);
      const cv = card.querySelector("canvas");
      if (state.charts[svc]) state.charts[svc].destroy();
      state.charts[svc] = new Chart(cv, chartConfig(hist));
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
    el.rootCauseSummary.textContent = a.probable_root_cause || "-";
    el.confidence.textContent = a.confidence_score || "-";
    el.riskWindow.textContent = a.risk_forecast?.predicted_breach_window || "-";
    el.humanSummary.textContent = a.human_summary || "-";
    el.reasoningJson.textContent = JSON.stringify({ causal_chain: a.causal_chain || [], corrective_actions: a.corrective_actions || [], preventive_hardening: a.preventive_hardening || [] }, null, 2);
    el.aiJson.textContent = JSON.stringify({ analysis: a, component_summary: c.component_summary || {} }, null, 2);

    const conf = deriveConfidenceBreakdown(data);
    el.confidenceBreakdown.innerHTML = `
      <span class="chip">Metric ${conf.metric}%</span>
      <span class="chip">Logs ${conf.logs}%</span>
      <span class="chip">Trace ${conf.trace}%</span>
      <span class="chip">Historical ${conf.historical}%</span>
    `;
    el.correlatedSignals.innerHTML = "";
    (a.causal_chain || ["No strong multi-signal causal chain detected"]).forEach((line) => {
      const li = document.createElement("li");
      li.textContent = line;
      el.correlatedSignals.appendChild(li);
    });
    el.serviceBadges.innerHTML = "";
    (c.components || []).forEach((s) => {
      const x = document.createElement("span");
      x.className = "chip";
      x.style.borderColor = s.status === "critical" ? "var(--crit)" : s.status === "warning" ? "var(--warn)" : "var(--ok)";
      x.textContent = `${s.service} • ${s.status}`;
      el.serviceBadges.appendChild(x);
    });
    const statsByService = {};
    (c.components || []).forEach((svc) => {
      const h = state.serviceHistory[svc.service];
      statsByService[svc.service] = {
        p95: h ? (h.p95.at(-1) || 0) : 0,
        err: h ? (h.err.at(-1) || 0) : 0,
        rps: h ? (h.rps.at(-1) || 0) : 0,
      };
    });
    renderDependencyMap(c.components || [], c.component_summary || {}, statsByService);
  }

  function renderDependencyMap(components, summary, statsByService) {
    const width = 700;
    const height = 320;
    const nodes = [
      { id: "api-gateway", x: 100, y: 170, status: "healthy" },
      { id: "ai-observer", x: 350, y: 50, status: summary.overall_status || "healthy" },
      { id: "postgres", x: 620, y: 170, status: "healthy" },
      ...components.map((c, i) => ({ id: c.service, x: 350, y: 150 + (i * 85), status: c.status }))
    ];
    const links = [
      ["api-gateway", "product-service"],
      ["api-gateway", "order-service"],
      ["product-service", "postgres"],
      ["order-service", "postgres"],
      ["ai-observer", "product-service"],
      ["ai-observer", "order-service"]
    ];
    const nodeColor = (s) => s === "critical" ? "#ef4444" : s === "warning" ? "#f59e0b" : "#22c55e";
    const edgeColor = (err) => err > 5 ? "#ef4444" : err > 1 ? "#f59e0b" : "#4f6f98";
    const edgeWidth = (p95) => p95 > 1000 ? 4 : p95 > 500 ? 3 : 2;

    let svg = `<rect width="${width}" height="${height}" fill="#0b1426"/>`;
    links.forEach(([a, b]) => {
      const na = nodes.find((n) => n.id === a);
      const nb = nodes.find((n) => n.id === b);
      if (!na || !nb) return;
      const keySvc = a.includes("-service") ? a : (b.includes("-service") ? b : "");
      const st = statsByService[keySvc] || { p95: 0, err: 0, rps: 0 };
      svg += `<line x1="${na.x}" y1="${na.y}" x2="${nb.x}" y2="${nb.y}" stroke="${edgeColor(st.err)}" stroke-width="${edgeWidth(st.p95)}">
          <title>${keySvc || `${a}->${b}`} | p95=${Math.round(st.p95)}ms | err=${st.err.toFixed(2)}% | rps=${st.rps.toFixed(2)}</title>
        </line>`;
    });

    nodes.forEach((n) => {
      const color = nodeColor(n.status);
      const pulse = n.status === "warning" || n.status === "critical";
      svg += `<g>
        <circle cx="${n.x}" cy="${n.y}" r="22" fill="#10203a" stroke="${color}" stroke-width="3">
          <title>${n.id} | status=${n.status}</title>
        </circle>
        <text x="${n.x}" y="${n.y + 36}" fill="#c3d5ef" font-size="11" text-anchor="middle">${n.id}</text>
      </g>`;
    });
    el.dependencyMap.innerHTML = svg;
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
    const arrow = recent > 0.1 ? "⬆" : recent < -0.1 ? "⬇" : "➡";
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
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: "#ffffff",
            borderColor: "#d7dee9",
            borderWidth: 1,
            titleColor: "#1f2937",
            bodyColor: "#1f2937",
          },
        },
        scales: {
          x: { ticks: { color: "#7a8799", maxTicksLimit: 8 }, grid: { color: "rgba(130,145,166,0.15)" } },
          y: { ticks: { color: "#7a8799" }, grid: { color: "rgba(130,145,166,0.15)" } }
        }
      }
    });
  }

  function renderRecentChanges(data) {
    const c = data.context || {};
    const k = c.kubernetes || {};
    const d = c.deployment || {};
    const list = [];
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
      item.innerHTML = `<strong>${e.label}</strong><small>${e.type} • ${e.ts.replace("T", " ").slice(0, 19)}Z</small>`;
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
    el.aiTabs.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
    document.getElementById("aiTabSignals").classList.toggle("hidden", tab !== "signals");
    document.getElementById("aiTabReasoning").classList.toggle("hidden", tab !== "reasoning");
    document.getElementById("aiTabJson").classList.toggle("hidden", tab !== "json");
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
      renderErrorTrend((data.context?.metrics?.error_rate_5xx_5m || 0) * 100);
      renderRecentChanges(data);

      const components = data.context?.components || [];
      await hydrateServiceTelemetry(components, namespace, severity);
      renderTelemetryCards(components);
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
    el.aiTabs.addEventListener("click", (e) => {
      if (e.target.tagName === "BUTTON") setAiTab(e.target.dataset.tab);
    });
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
    bindEvents();
    enforceRbac();
    setMainView("telemetry");
    setAiTab("signals");
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
