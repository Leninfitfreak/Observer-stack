export function createStore(initialState) {
  let state = structuredClone(initialState);
  const listeners = new Set();

  const getState = () => state;

  const setState = (patch) => {
    const next = typeof patch === 'function' ? patch(state) : { ...state, ...patch };
    state = next;
    listeners.forEach((listener) => listener(state));
  };

  const subscribe = (listener) => {
    listeners.add(listener);
    return () => listeners.delete(listener);
  };

  return { getState, setState, subscribe };
}

export function createConsoleState(config) {
  return createStore({
    selectedService: 'all',
    focusMode: false,
    selectedTimeRange: null,
    incidentWindow: { minutes: config.incidentWindowMinutes },
    zoomState: {
      map: { scale: 1, tx: 0, ty: 0 },
      metrics: null,
    },
    fullscreenPanel: null,
    crosshairIndex: null,
    anomaly: null,
    data: null,
  });
}
