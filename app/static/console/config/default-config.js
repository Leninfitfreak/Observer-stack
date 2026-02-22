export const defaultConsoleConfig = {
  refreshMs: 20000,
  animationMs: 180,
  incidentWindowMinutes: 30,
  severityColors: {
    healthy: '#22c55e',
    warning: '#f59e0b',
    degraded: '#f97316',
    critical: '#ef4444',
    unknown: '#64748b',
  },
  map: {
    minScale: 0.4,
    maxScale: 3.0,
    zoomStep: 1.15,
    nodeRadius: {
      service: 24,
      pod: 14,
    },
  },
  metrics: {
    maxPoints: 240,
    zoomWheel: { enabled: true },
    dragZoom: { enabled: true, mode: 'x' },
  },
};
