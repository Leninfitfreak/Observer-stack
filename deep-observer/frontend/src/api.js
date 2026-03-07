const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8081";

function withQuery(path, params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== "" && value !== null && value !== undefined) {
      query.set(key, value);
    }
  });
  const qs = query.toString();
  return `${API_BASE_URL}${path}${qs ? `?${qs}` : ""}`;
}

async function request(path, params) {
  const response = await fetch(withQuery(path, params));
  if (!response.ok) {
    throw new Error(`Request failed for ${path}`);
  }
  return response.json();
}

export function fetchIncidents(filters) {
  return request("/api/incidents", { ...filters, limit: 200 });
}

export function fetchIncident(incidentId) {
  return request(`/api/incidents/${incidentId}`);
}

export function fetchTimeline(incidentId) {
  return request(`/api/incidents/${incidentId}/timeline`);
}

export function fetchTopology(filters) {
  return request("/api/topology", filters);
}

export function fetchFilters() {
  return request("/api/filters");
}

export function fetchServiceHealth(filters) {
  return request("/api/service-health", { ...filters, limit: 300 });
}

export function fetchClusterReport(filters) {
  return request("/api/cluster-report", filters);
}

export function fetchProblems(filters) {
  return request("/api/problems", { ...filters, limit: 200 });
}

export function fetchChanges(filters) {
  return request("/api/changes", { ...filters, limit: 200 });
}

export function fetchSLOStatus(filters) {
  return request("/api/slo-status", { ...filters, limit: 300 });
}

export function fetchRunbooks(filters) {
  return request("/api/runbooks", { ...filters, limit: 100 });
}

export function fetchObservabilityReport(filters) {
  return request("/api/observability-report", filters);
}
