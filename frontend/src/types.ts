export interface IncidentAnalysis {
  id: number;
  incident_id: string;
  service_name: string;
  anomaly_score: number;
  confidence_score: number;
  classification: string;
  root_cause: string;
  mitigation: any;
  risk_forecast: number;
  mitigation_success?: boolean;
  created_at: string;
}

export interface IncidentListResponse {
  total: number;
  limit: number;
  offset: number;
  items: IncidentAnalysis[];
}

export interface IncidentSummaryResponse {
  total_incidents: number;
  avg_anomaly_score: number;
  avg_confidence_score: number;
  classification_distribution: Record<string, number>;
  top_mitigation: string;
}

export interface HistoryFiltersState {
  startDate: string;
  endDate: string;
  serviceName: string;
  classification: string;
  minConfidence: number;
}
