package v2

import (
	"time"

	"deep-observer/ai-core/internal/incidents"
)

type ScopeRequest struct {
	Cluster   string
	Namespace string
	Service   string
	Start     time.Time
	End       time.Time
}

type Scope struct {
	Cluster   string    `json:"cluster"`
	Namespace string    `json:"namespace"`
	Service   string    `json:"service"`
	Start     time.Time `json:"start"`
	End       time.Time `json:"end"`
}

type FilterOptions struct {
	Clusters   []string `json:"clusters"`
	Namespaces []string `json:"namespaces"`
	Services   []string `json:"services"`
}

type TopologyNode struct {
	ID       string `json:"id"`
	Label    string `json:"label"`
	NodeType string `json:"node_type"`
}

type TopologyEdge struct {
	Source         string  `json:"source"`
	Target         string  `json:"target"`
	DependencyType string  `json:"dependency_type"`
	CallCount      int64   `json:"call_count"`
	ErrorRate      float64 `json:"error_rate"`
	LatencyMs      float64 `json:"latency_ms"`
}

type Topology struct {
	Available bool           `json:"available"`
	Nodes     []TopologyNode `json:"nodes"`
	Edges     []TopologyEdge `json:"edges"`
}

type DashboardSummary struct {
	TotalIncidents      int `json:"total_incidents"`
	ObservedIncidents   int `json:"observed_incidents"`
	PredictiveIncidents int `json:"predictive_incidents"`
	TopologyNodes       int `json:"topology_nodes"`
	TopologyEdges       int `json:"topology_edges"`
}

type DashboardResponse struct {
	NormalizedScope Scope            `json:"normalized_scope"`
	FilterOptions   FilterOptions    `json:"filter_options"`
	IncidentList    []incidents.Incident `json:"incident_list"`
	ScopedTopology  Topology         `json:"scoped_topology"`
	Summary         DashboardSummary `json:"summary"`
	Empty           bool             `json:"empty"`
	Message         string           `json:"message"`
}

type EvidenceDirect struct {
	RequestCount      int64              `json:"request_count"`
	LogCount          int64              `json:"log_count"`
	TraceSampleCount  int64              `json:"trace_sample_count"`
	ErrorRate         float64            `json:"error_rate"`
	P95LatencyMs      float64            `json:"p95_latency_ms"`
	MetricHighlights  map[string]float64 `json:"metric_highlights"`
	ErrorLogSamples   []string           `json:"error_log_samples"`
	TraceIDs          []string           `json:"trace_ids"`
}

type EvidenceContextual struct {
	Topology  string `json:"topology"`
	Database  string `json:"database"`
	Messaging string `json:"messaging"`
}

type ReasoningView struct {
	Status         string   `json:"status"`
	Allowed        bool     `json:"allowed"`
	ExecutionMode  string   `json:"execution_mode"`
	Summary        string   `json:"summary"`
	RootCause      string   `json:"root_cause"`
	RootCauseSignal string  `json:"root_cause_signal"`
	Confidence     float64  `json:"confidence"`
	Actions        []string `json:"actions"`
	Error          string   `json:"error"`
}

type SparsePredictiveView struct {
	Summary              string             `json:"summary"`
	SignalSet            []string           `json:"signal_set"`
	AnomalyScore         float64            `json:"anomaly_score"`
	DirectEvidence       EvidenceDirect     `json:"direct_evidence"`
	ContextualEvidence   EvidenceContextual `json:"contextual_evidence"`
	NearestObserved      []incidents.Incident `json:"nearest_observed"`
	NextSteps            []string           `json:"next_steps"`
}

type IncidentViewResponse struct {
	Incident           incidents.Incident  `json:"incident"`
	NormalizedScope    Scope               `json:"normalized_scope"`
	State              string              `json:"state"`
	DirectEvidence     EvidenceDirect      `json:"direct_evidence"`
	ContextualEvidence EvidenceContextual  `json:"contextual_evidence"`
	MissingEvidence    []string            `json:"missing_evidence"`
	Signals            []string            `json:"signals"`
	AnomalyScore       float64             `json:"anomaly_score"`
	IncidentTopology   Topology            `json:"incident_topology"`
	ImpactedServices   []string            `json:"impacted_services"`
	PropagationPath    []string            `json:"propagation_path"`
	RelatedIncidents   []incidents.Incident `json:"related_incidents"`
	ObservabilityScore float64             `json:"observability_score"`
	Sparse             bool                `json:"sparse"`
	Reasoning          ReasoningView       `json:"reasoning"`
	SparsePredictive   *SparsePredictiveView `json:"sparse_predictive,omitempty"`
}

