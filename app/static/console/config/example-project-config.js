import { defaultConsoleConfig } from '../config/default-config.js';

export const fintechConsoleConfig = {
  ...defaultConsoleConfig,
  refreshMs: 10000,
  incidentWindowMinutes: 60,
  map: {
    ...defaultConsoleConfig.map,
    maxScale: 4.0,
  },
  metrics: {
    ...defaultConsoleConfig.metrics,
    maxPoints: 480,
  },
};
