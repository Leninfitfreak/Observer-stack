export interface IncidentAnalysis {
  incident_id: string;
  status: string;
  severity: string;
  impact_level: string;
  slo_breach_risk: number;
  error_budget_remaining: number;
  affected_services: string;
  start_time: string;
  duration: string;
  executive_summary?: string | null;
  root_cause?: string | null;
  confidence_score: number;
  classification?: string | null;
  risk_forecast?: number | null;
  created_at: string;
}

export interface IncidentListResponse {
  data: IncidentAnalysis[];
  total_count: number;
  limit: number;
  offset: number;
}

export interface IncidentSummaryResponse {
  totalIncidents: number;
  avgConfidence: number;
  mostCommonClassification: string;
  topMitigation: string;
}

export interface HistoryFiltersState {
  startDate: string;
  endDate: string;
  service: string;
  classification: string;
  minConfidence: number;
}

export interface IncidentDetailResponse {
  incident: Record<string, any>;
  analysis: Array<Record<string, any>>;
  metrics_snapshot: Array<Record<string, any>>;
  status_history: Array<Record<string, any>>;
}
