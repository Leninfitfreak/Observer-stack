const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8081";

function normalizeScopeValue(value) {
  if (typeof value !== "string") return value;
  const trimmed = value.trim();
  const lowered = trimmed.toLowerCase();
  if (!trimmed || lowered === "all" || lowered === "all clusters" || lowered === "all namespaces" || lowered === "all services") {
    return "";
  }
  return trimmed;
}

function withQuery(path, params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (["cluster", "namespace", "service"].includes(key)) {
      value = normalizeScopeValue(value);
    }
    if (value !== undefined && value !== null && value !== "") {
      query.set(key, value);
    }
  });
  const qs = query.toString();
  return `${API_BASE_URL}${path}${qs ? `?${qs}` : ""}`;
}

async function request(path, params = {}, options = {}) {
  const response = await fetch(withQuery(path, params), options);
  if (!response.ok) {
    throw new Error(`Request failed: ${path}`);
  }
  return response.json();
}

export function fetchDashboardV2(filters) {
  return request("/api/v2/dashboard", filters);
}

export function fetchIncidentViewV2(incidentId, filters) {
  return request(`/api/v2/incidents/${incidentId}/view`, filters);
}

export function fetchIncidentV2(incidentId) {
  return request(`/api/v2/incidents/${incidentId}`);
}

export function runReasoningV2(incidentId) {
  return request(`/api/v2/incidents/${incidentId}/reasoning/run`, {}, { method: "POST" });
}

export function retryReasoningV2(incidentId) {
  return request(`/api/v2/incidents/${incidentId}/reasoning/retry`, {}, { method: "POST" });
}

export function fetchReasoningHistoryV2(incidentId) {
  return request(`/api/v2/incidents/${incidentId}/reasoning/history`);
}

