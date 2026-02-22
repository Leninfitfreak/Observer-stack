import { defaultConsoleConfig } from '../config/default-config.js';
import { ComponentContainer } from '../components/component-container.js';
import { DependencyMap } from './dependency-map.js';
import { MetricsStack } from './metrics-stack.js';
import { fetchReasoningSnapshot } from './api-client.js';
import { buildMetricsPoint } from './transform.js';

export class IncidentConsole {
  constructor({ root, store, config = defaultConsoleConfig }) {
    this.root = root;
    this.store = store;
    this.config = config;
    this.timer = null;

    this.state = {
      namespace: 'dev',
      service: 'all',
      severity: 'warning',
      timeWindow: `${config.incidentWindowMinutes}m`,
    };

    this.metricsByService = {};
    this._buildLayout();
    this._bindGlobalEvents();
  }

  _buildLayout() {
    this.root.innerHTML = '';
    this.root.className = 'console-grid';

    this.header = document.createElement('section');
    this.header.className = 'incident-header-v2';
    this.header.innerHTML = `
      <div class="incident-grid" id="incidentGrid"></div>
      <div class="controls-row">
        <label>Namespace <input id="nsInput" value="${this.state.namespace}" /></label>
        <label>Service <input id="svcInput" value="${this.state.service}" /></label>
        <label>Severity <select id="sevInput"><option>warning</option><option>critical</option><option>info</option></select></label>
        <label>Time Window <select id="twInput"><option>5m</option><option>15m</option><option selected>30m</option><option>1h</option><option>6h</option></select></label>
        <button id="refreshBtn" type="button">Refresh</button>
        <button id="resetViewBtn" type="button">Reset View</button>
      </div>
      <div class="focus-banner" id="focusBanner"></div>
    `;

    this.depContainer = new ComponentContainer({
      title: 'Dependency Map',
      id: 'dependency-map',
      onFullscreenToggle: (id) => this.toggleFullscreen(id),
      onReset: () => this.resetAllViews(),
    });

    this.metricsContainer = new ComponentContainer({
      title: 'Metrics Stack',
      id: 'metrics',
      onFullscreenToggle: (id) => this.toggleFullscreen(id),
      onReset: () => this.resetAllViews(),
    });

    this.root.append(this.header, this.depContainer.root, this.metricsContainer.root);

    this.depMap = new DependencyMap({
      mount: this.depContainer.body,
      store: this.store,
      config: this.config,
      onFocusService: (svc) => this.store.setState((s) => ({ ...s, selectedService: svc, focusMode: true })),
    });

    this.metrics = new MetricsStack({
      mount: this.metricsContainer.body,
      store: this.store,
      config: this.config,
    });

    this.nsInput = this.header.querySelector('#nsInput');
    this.svcInput = this.header.querySelector('#svcInput');
    this.sevInput = this.header.querySelector('#sevInput');
    this.twInput = this.header.querySelector('#twInput');
    this.focusBanner = this.header.querySelector('#focusBanner');
    this.incidentGrid = this.header.querySelector('#incidentGrid');

    this.header.querySelector('#refreshBtn').addEventListener('click', () => this.refresh());
    this.header.querySelector('#resetViewBtn').addEventListener('click', () => this.resetAllViews());

    this.store.subscribe((state) => {
      this.root.classList.toggle('fullscreen-dependency', state.fullscreenPanel === 'dependency-map');
      this.root.classList.toggle('fullscreen-metrics', state.fullscreenPanel === 'metrics');
      this.focusBanner.textContent = state.focusMode && state.selectedService !== 'all'
        ? `Focus Mode: ${state.selectedService} (ESC to exit fullscreen, Reset Focus in map toolbar)`
        : '';
    });
  }

  _bindGlobalEvents() {
    document.addEventListener('keydown', (ev) => {
      if (ev.key === 'Escape') {
        this.store.setState((s) => ({ ...s, fullscreenPanel: null }));
      }
    });
  }

  toggleFullscreen(id) {
    this.store.setState((s) => ({ ...s, fullscreenPanel: s.fullscreenPanel === id ? null : id }));
  }

  resetAllViews() {
    this.depMap.resetView();
    this.metrics.charts.forEach((chart) => chart.resetZoom());
    this.store.setState((s) => ({
      ...s,
      selectedService: 'all',
      focusMode: false,
      selectedTimeRange: null,
      crosshairIndex: null,
      fullscreenPanel: null,
    }));
  }

  _renderIncidentSummary(snapshot) {
    const alert = snapshot?.context?.alert || {};
    const analysis = snapshot?.analysis || {};
    const summaryItems = [
      ['Incident ID', `INC-${Math.floor(Date.now() / 1000).toString().slice(-6)}`],
      ['Status', analysis.impact_level ? 'INVESTIGATING' : 'MONITORING'],
      ['Severity', String(alert.severity || 'warning').toUpperCase()],
      ['Service Scope', alert.service || 'all'],
      ['Root Cause', analysis.probable_root_cause || '-'],
      ['AI Confidence', analysis.confidence_score || '-'],
      ['Risk', analysis.risk_forecast?.predicted_breach_window || '-'],
      ['Policy', analysis.policy_note || '-'],
    ];

    this.incidentGrid.innerHTML = '';
    summaryItems.forEach(([k, v]) => {
      const card = document.createElement('article');
      card.className = 'incident-card';
      card.innerHTML = `<span>${k}</span><strong>${v}</strong>`;
      this.incidentGrid.appendChild(card);
    });
  }

  _deriveAnomaly(snapshot, series) {
    const anomalies = snapshot?.context?.metrics?.anomalies || [];
    if (!anomalies.length || !series.length) return null;
    const end = series.length - 1;
    const start = Math.max(0, end - Math.min(10, series.length - 1));
    return { start, end };
  }

  async refresh() {
    this.depContainer.setLoading(true, 'Loading topology...');
    this.metricsContainer.setLoading(true, 'Loading metrics...');

    this.state.namespace = this.nsInput.value.trim() || 'dev';
    this.state.service = this.svcInput.value.trim() || 'all';
    this.state.severity = this.sevInput.value;
    this.state.timeWindow = this.twInput.value;

    try {
      const snapshot = await fetchReasoningSnapshot({
        namespace: this.state.namespace,
        service: this.state.service,
        severity: this.state.severity,
        timeWindow: this.state.timeWindow,
      });

      this.store.setState((s) => ({ ...s, data: snapshot }));
      this._renderIncidentSummary(snapshot);

      const selected = this.state.service === 'all' ? 'all' : this.state.service;
      const point = buildMetricsPoint(snapshot);
      this.metrics.pushSnapshot(selected, point);
      if (selected !== 'all') {
        this.metrics.pushSnapshot('all', point);
      }

      this.metricsByService[selected] = point;
      const anomalyRange = this._deriveAnomaly(snapshot, this.metrics.series.get(selected) || []);
      const anomalyService = this.store.getState().selectedService !== 'all'
        ? this.store.getState().selectedService
        : (snapshot?.context?.components || []).find((c) => c.status !== 'healthy')?.service || null;

      this.store.setState((s) => ({
        ...s,
        anomaly: anomalyRange,
        incidentWindow: { minutes: parseInt(this.state.timeWindow, 10) || this.config.incidentWindowMinutes },
      }));

      this.depMap.setData({
        wiring: snapshot?.context?.cluster_wiring || { nodes: [], edges: [] },
        metricsByService: this.metricsByService,
        anomalyService,
      });

      this.metrics.setAnomalyWindow(anomalyRange, anomalyRange?.end ?? null);
      this.metrics.render(this.store.getState());

      if (anomalyService) {
        this.store.setState((s) => ({ ...s, selectedService: anomalyService, focusMode: true }));
      }

      this.depContainer.setLoading(false);
      this.metricsContainer.setLoading(false);
      this.depContainer.clearError();
      this.metricsContainer.clearError();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      this.depContainer.setError(msg);
      this.metricsContainer.setError(msg);
      this.depContainer.setLoading(false);
      this.metricsContainer.setLoading(false);
    }
  }

  start() {
    this.refresh();
    clearInterval(this.timer);
    this.timer = setInterval(() => this.refresh(), this.config.refreshMs);
  }

  stop() {
    clearInterval(this.timer);
    this.depMap.destroy();
    this.metrics.destroy();
  }
}
