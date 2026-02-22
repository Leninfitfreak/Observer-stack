import { createConsoleState } from '../state/store.js';
import { IncidentConsole } from '../modules/incident-console.js';
import { fintechConsoleConfig } from '../config/example-project-config.js';

export function mountConsoleForProject(rootElement) {
  const store = createConsoleState(fintechConsoleConfig);
  const app = new IncidentConsole({ root: rootElement, store, config: fintechConsoleConfig });
  app.start();
  return app;
}
