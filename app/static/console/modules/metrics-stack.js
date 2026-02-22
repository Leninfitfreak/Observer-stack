const chartInstances = [];

const syncCrosshairPlugin = {
  id: 'syncCrosshairPlugin',
  afterDraw(chart, _args, pluginOptions) {
    const idx = pluginOptions?.getCrosshairIndex?.();
    if (idx == null) return;
    const xScale = chart.scales.x;
    if (!xScale) return;
    const x = xScale.getPixelForValue(idx);
    const { ctx, chartArea } = chart;
    if (!chartArea) return;
    ctx.save();
    ctx.strokeStyle = '#8fb1d9';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, chartArea.top);
    ctx.lineTo(x, chartArea.bottom);
    ctx.stroke();
    ctx.restore();
  },
};

Chart.register(syncCrosshairPlugin);

function makeDataset(label, color, key, yAxisID = 'y') {
  return {
    label,
    key,
    borderColor: color,
    backgroundColor: `${color}22`,
    borderWidth: 2,
    pointRadius: 0,
    tension: 0.22,
    yAxisID,
    data: [],
  };
}

export class MetricsStack {
  constructor({ mount, store, config }) {
    this.mount = mount;
    this.store = store;
    this.config = config;
    this.series = new Map();
    this.canvases = new Map();
    this.charts = new Map();
    this.anomalyWindow = null;
    this.incidentTs = null;

    this.root = document.createElement('div');
    this.root.className = 'metrics-stack';
    mount.appendChild(this.root);

    this._createChart('latency', 'Latency (P95/P99)', [
      makeDataset('P95 (ms)', '#56A64B', 'p95Ms'),
      makeDataset('P99 (ms)', '#9BCB93', 'p99Ms'),
    ]);
    this._createChart('errors', 'Error Rate (%)', [makeDataset('5xx (%)', '#ef4444', 'errorPct')]);
    this._createChart('throughput', 'Throughput (RPS)', [makeDataset('RPS', '#38bdf8', 'rps')]);
    this._createChart('resource', 'CPU / Memory', [
      makeDataset('CPU (%)', '#f59e0b', 'cpuPct', 'y'),
      makeDataset('Mem (MB)', '#a78bfa', 'memMb', 'y1'),
    ]);

    this.unsubscribe = store.subscribe((state) => {
      this.root.classList.toggle('is-fullscreen', state.fullscreenPanel === 'metrics');
      this.render(state);
    });
  }

  destroy() {
    this.unsubscribe?.();
    this.charts.forEach((chart) => chart.destroy());
    this.charts.clear();
  }

  _createChart(key, title, datasets) {
    const card = document.createElement('div');
    card.className = 'metric-card';
    const h = document.createElement('h4');
    h.textContent = title;
    const canvas = document.createElement('canvas');
    card.append(h, canvas);
    this.root.appendChild(card);

    const chart = new Chart(canvas, {
      type: 'line',
      data: {
        labels: [],
        datasets: datasets.map((d) => ({ ...d })),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        animation: false,
        parsing: false,
        normalized: true,
        plugins: {
          legend: { labels: { color: '#91a4c4' } },
          zoom: {
            zoom: {
              wheel: this.config.metrics.zoomWheel,
              drag: this.config.metrics.dragZoom,
              mode: 'x',
              onZoomComplete: ({ chart }) => this._onZoom(chart),
            },
            pan: {
              enabled: true,
              mode: 'x',
              onPanComplete: ({ chart }) => this._onZoom(chart),
            },
          },
          syncCrosshairPlugin: {
            getCrosshairIndex: () => this.store.getState().crosshairIndex,
          },
          tooltip: {
            enabled: true,
            callbacks: {
              footer: (ctx) => `timestamp: ${ctx[0]?.label || '-'}`,
            },
          },
        },
        scales: {
          x: { ticks: { color: '#7f94b8' }, grid: { color: 'rgba(130,145,166,0.15)' } },
          y: { ticks: { color: '#7f94b8' }, grid: { color: 'rgba(130,145,166,0.15)' } },
          y1: { position: 'right', display: key === 'resource', ticks: { color: '#7f94b8' }, grid: { drawOnChartArea: false } },
        },
      },
      plugins: [{
        id: 'incidentOverlay',
        beforeDatasetsDraw: (chart) => {
          const state = this.store.getState();
          const range = state.selectedTimeRange || this.anomalyWindow;
          if (!range || range.start == null || range.end == null) return;
          const xScale = chart.scales.x;
          const left = xScale.getPixelForValue(range.start);
          const right = xScale.getPixelForValue(range.end);
          const { ctx, chartArea } = chart;
          ctx.save();
          ctx.fillStyle = 'rgba(239,68,68,0.08)';
          ctx.fillRect(left, chartArea.top, Math.max(1, right - left), chartArea.bottom - chartArea.top);
          ctx.strokeStyle = 'rgba(239,68,68,0.7)';
          ctx.beginPath();
          ctx.moveTo(left, chartArea.top);
          ctx.lineTo(left, chartArea.bottom);
          ctx.stroke();
          if (this.incidentTs != null) {
            const ix = xScale.getPixelForValue(this.incidentTs);
            ctx.strokeStyle = 'rgba(245,158,11,0.95)';
            ctx.beginPath();
            ctx.moveTo(ix, chartArea.top);
            ctx.lineTo(ix, chartArea.bottom);
            ctx.stroke();
          }
          ctx.restore();
        },
      }],
    });

    canvas.addEventListener('dblclick', () => {
      chart.resetZoom();
      this.store.setState((s) => ({ ...s, selectedTimeRange: null }));
    });

    canvas.addEventListener('mousemove', (ev) => {
      const points = chart.getElementsAtEventForMode(ev, 'index', { intersect: false }, false);
      if (!points.length) return;
      const idx = points[0].index;
      this.store.setState((s) => ({ ...s, crosshairIndex: idx }));
    });

    chartInstances.push(chart);
    this.canvases.set(key, canvas);
    this.charts.set(key, chart);
  }

  _onZoom(chart) {
    const x = chart.scales.x;
    const range = { start: Math.round(x.min), end: Math.round(x.max) };
    this.store.setState((s) => ({ ...s, selectedTimeRange: range, zoomState: { ...s.zoomState, metrics: range } }));
    this.charts.forEach((c) => {
      if (c === chart) return;
      c.zoomScale('x', { min: range.start, max: range.end }, 'none');
      c.update('none');
    });
  }

  pushSnapshot(service, point) {
    if (!this.series.has(service)) this.series.set(service, []);
    const arr = this.series.get(service);
    arr.push(point);
    if (arr.length > this.config.metrics.maxPoints) arr.splice(0, arr.length - this.config.metrics.maxPoints);
  }

  setAnomalyWindow(windowRange, incidentTs) {
    this.anomalyWindow = windowRange;
    this.incidentTs = incidentTs;
  }

  render(state) {
    const service = state.selectedService === 'all' ? 'all' : state.selectedService;
    const points = this.series.get(service) || [];
    const labels = points.map((p, idx) => idx);

    this.charts.forEach((chart) => {
      chart.data.labels = labels;
      chart.data.datasets.forEach((dataset) => {
        dataset.data = points.map((p) => ({ x: points.indexOf(p), y: p[dataset.key] || 0 }));
      });
      chart.update('none');
    });

    if (state.selectedTimeRange) {
      this.charts.forEach((chart) => {
        chart.zoomScale('x', state.selectedTimeRange, 'none');
      });
    }
  }
}
