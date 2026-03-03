package problem

import "time"

type Problem struct {
	ProblemID          string         `json:"problem_id"`
	ProjectID          string         `json:"project_id"`
	Cluster            string         `json:"cluster"`
	Namespace          string         `json:"namespace"`
	Service            string         `json:"service"`
	RootCauseEntity    string         `json:"root_cause_entity"`
	ImpactedEntities   []string       `json:"impacted_entities"`
	Severity           string         `json:"severity"`
	Confidence         float64        `json:"confidence"`
	CausalChain        []string       `json:"causal_chain"`
	CorrelatedSignals  []string       `json:"correlated_signals"`
	ImpactAssessment   string         `json:"impact_assessment"`
	RecommendedActions []string       `json:"recommended_actions"`
	StartTime          time.Time      `json:"start_time"`
	EndTime            time.Time      `json:"end_time"`
	CreatedAt          time.Time      `json:"created_at"`
	AnomalyScore       float64        `json:"anomaly_score"`
	MetricsSummary     map[string]any `json:"metrics_summary"`
	LogsSummary        map[string]any `json:"logs_summary"`
	TraceSummary       map[string]any `json:"trace_summary"`
}
