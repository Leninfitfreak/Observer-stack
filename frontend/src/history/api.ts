import type { IncidentListResponse, IncidentSummaryResponse } from "../types";

const API_BASE = "";

function buildQuery(params: Record<string, string | number | undefined>): string {
  const qp = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === "") {
      return;
    }
    qp.set(key, String(value));
  });
  return qp.toString();
}

export async function fetchIncidentAnalysis(params: {
  start_date: string;
  end_date: string;
  service_name?: string;
  classification?: string;
  min_confidence?: number;
  anomaly_score_min?: number;
  anomaly_score_max?: number;
  limit?: number;
  offset?: number;
}): Promise<IncidentListResponse> {
  const query = buildQuery(params);
  const res = await fetch(`${API_BASE}/incident-analysis?${query}`);
  if (!res.ok) {
    throw new Error(`Failed loading incidents: ${res.status}`);
  }
  return res.json();
}

export async function fetchIncidentSummary(params: {
  start_date: string;
  end_date: string;
  service_name?: string;
  classification?: string;
  min_confidence?: number;
}): Promise<IncidentSummaryResponse> {
  const query = buildQuery(params);
  const res = await fetch(`${API_BASE}/incident-analysis/summary?${query}`);
  if (!res.ok) {
    throw new Error(`Failed loading summary: ${res.status}`);
  }
  return res.json();
}
