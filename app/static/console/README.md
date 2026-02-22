# Incident Command Console Frontend

## Reusable folder structure

```text
app/static/console/
  components/component-container.js
  modules/
    incident-console.js
    dependency-map.js
    metrics-stack.js
    api-client.js
    transform.js
  state/store.js
  config/
    default-config.js
    example-project-config.js
  integration/
    example-adapter.js
  styles/console.css
```

## Dependency injection and state flow

- `main.js` composes `store + config + IncidentConsole`
- `IncidentConsole` composes feature modules
- Feature modules communicate only through shared state

## LLM/provider backend switching

Backend already switches via env config:
- `LLM_PROVIDER=ollama`
- `LLM_PROVIDER=openai`

No frontend change needed.

## Plug into another project

Use:

```js
import { mountConsoleForProject } from '/static/console/integration/example-adapter.js';
const app = mountConsoleForProject(document.getElementById('root'));
```

## Controls implemented

- Dependency map: wheel zoom, pinch zoom, pan, dblclick zoom, fit, reset, focus mode, fullscreen.
- Metrics stack: drag zoom, pan, dblclick reset, crosshair sync, anomaly overlay, AI marker.
- Shared state: selected service, time range, incident window, zoom state, fullscreen state.
