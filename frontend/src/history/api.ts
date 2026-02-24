import type { IncidentDetailResponse, IncidentListResponse, IncidentSummaryResponse } from "../types";

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
  service?: string;
  classification?: string;
  min_confidence?: number;
  limit?: number;
  offset?: number;
}): Promise<IncidentListResponse> {
  const query = buildQuery(params);
  const res = await fetch(`${API_BASE}/api/incidents?${query}`);
  if (!res.ok) {
    throw new Error(`Failed loading incidents: ${res.status}`);
  }
  return res.json();
}

export async function fetchIncidentSummary(params: {
  start_date: string;
  end_date: string;
  service?: string;
  classification?: string;
  min_confidence?: number;
}): Promise<IncidentSummaryResponse> {
  const query = buildQuery({ ...params, limit: 500, offset: 0 });
  const res = await fetch(`${API_BASE}/api/incidents?${query}`);
  if (!res.ok) {
    throw new Error(`Failed loading summary: ${res.status}`);
  }
  const payload: IncidentListResponse = await res.json();
  const total = payload.total_count || 0;
  const confidences = payload.data.map((x) => Number(x.confidence_score || 0));
  const avgConf = confidences.length ? confidences.reduce((a, b) => a + b, 0) / confidences.length : 0;
  const dist: Record<string, number> = {};
  payload.data.forEach((item) => {
    const k = item.classification || "Unknown";
    dist[k] = (dist[k] || 0) + 1;
  });
  const topClass = Object.entries(dist).sort((a, b) => b[1] - a[1])[0]?.[0] || "-";
  return {
    totalIncidents: total,
    avgConfidence: avgConf,
    mostCommonClassification: topClass,
    topMitigation: "-",
  };
}

export async function getReportExcel(params: {
  start_date: string;
  end_date: string;
  service?: string;
  classification?: string;
  min_confidence?: number;
}): Promise<Blob> {
  const res = await fetch(`${API_BASE}/api/incidents/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    throw new Error(`Failed generating report: ${res.status}`);
  }
  return res.blob();
}

export async function fetchIncidentDetails(incidentId: string): Promise<IncidentDetailResponse> {
  const res = await fetch(`${API_BASE}/api/incidents/${encodeURIComponent(incidentId)}`);
  if (!res.ok) {
    throw new Error(`Failed loading incident details: ${res.status}`);
  }
  return res.json();
}
