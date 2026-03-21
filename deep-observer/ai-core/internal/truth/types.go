package truth

import (
	"time"

	"deep-observer/ai-core/internal/clickhouse"
	"deep-observer/ai-core/internal/incidents"
)

type ScopeRequest struct {
	Cluster   string
	Namespace string
	Service   string
	Start     time.Time
	End       time.Time
}

type NormalizedScope struct {
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

type SummaryCounts struct {
	TotalIncidents      int `json:"total_incidents"`
	ObservedIncidents   int `json:"observed_incidents"`
	PredictiveIncidents int `json:"predictive_incidents"`
	TopologyNodes       int `json:"topology_nodes"`
	TopologyEdges       int `json:"topology_edges"`
}

type NoResultsState struct {
	Empty   bool   `json:"empty"`
	Message string `json:"message"`
}

type DashboardContract struct {
	NormalizedScope NormalizedScope          `json:"normalized_scope"`
	FilterOptions   FilterOptions            `json:"filter_options"`
	IncidentList    []incidents.Incident     `json:"incident_list"`
	ScopedTopology  clickhouse.TopologyGraph `json:"scoped_topology"`
	SummaryCounts   SummaryCounts            `json:"summary_counts"`
	NoResultsState  NoResultsState           `json:"no_results_state"`
}

type SelectedIncidentContract map[string]any
