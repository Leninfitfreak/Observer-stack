import { defaultConsoleConfig } from './config/default-config.js';
import { createConsoleState } from './state/store.js';
import { IncidentConsole } from './modules/incident-console.js';

function boot() {
  const root = document.getElementById('incidentConsoleRoot');
  if (!root) return;
  const store = createConsoleState(defaultConsoleConfig);
  const consoleApp = new IncidentConsole({ root, store, config: defaultConsoleConfig });
  consoleApp.start();
  window.__incidentConsole = consoleApp;
}

boot();
