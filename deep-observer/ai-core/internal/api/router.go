package api

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"

	"deep-observer/ai-core/internal/clickhouse"
	"deep-observer/ai-core/internal/config"
	"deep-observer/ai-core/internal/enterprise"
	"deep-observer/ai-core/internal/incidents"
)

var serviceNodePattern = regexp.MustCompile(`^[a-z0-9][a-z0-9._/-]{0,127}$`)
var structuredTopologyNodePattern = regexp.MustCompile(`^(?:[a-z0-9][a-z0-9._/-]{0,127}|db:[a-z0-9][a-z0-9._/-]{0,95}|messaging:[a-z0-9][a-z0-9._/-]{0,95})$`)

func NewRouter(store *incidents.Store, chConfig config.ClickHouseConfig, project config.ProjectConfig) http.Handler {
	sloEngine := enterprise.NewSLOEngine(store)
	coverageEngine := enterprise.NewObservabilityCoverageAnalyzer(store)
	mux := http.NewServeMux()
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
	})

	mux.HandleFunc("/api/incidents", func(w http.ResponseWriter, r *http.Request) {
		ctx, cancel := context.WithTimeout(r.Context(), 20*time.Second)
		defer cancel()
		clusterFilter := firstNonEmpty(r.URL.Query().Get("cluster"), project.ClusterID)
		namespaceFilter := firstNonEmpty(r.URL.Query().Get("namespace"), project.NamespaceFilter)
		serviceFilter := normalizeServiceName(firstNonEmpty(r.URL.Query().Get("service"), project.ServiceFilter))
		logFilters("incidents", clusterFilter, namespaceFilter, serviceFilter, r.URL.Query().Get("start"), r.URL.Query().Get("end"), r.URL.Query().Get("time_range"))

		items, err := store.ListIncidents(ctx, incidents.QueryFilters{
			ProjectID: firstNonEmpty(r.URL.Query().Get("project_id"), project.ProjectID),
			Cluster:   clusterFilter,
			Namespace: namespaceFilter,
			Service:   serviceFilter,
			ProblemID: r.URL.Query().Get("problem_id"),
			Start:     parseOptionalTime(r.URL.Query().Get("start")),
			End:       parseOptionalTime(r.URL.Query().Get("end")),
			Limit:     parseLimit(r.URL.Query().Get("limit"), 100),
		})
		if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
			return
		}
		filtered := make([]incidents.Incident, 0, len(items))
		for _, item := range items {
			if clickhouse.IsIgnoredService(item.Service) {
				continue
			}
			filtered = append(filtered, item)
		}
		fmt.Printf("api incidents result_count=%d\n", len(filtered))
		writeJSON(w, http.StatusOK, filtered)
	})

	mux.HandleFunc("/api/incidents/", func(w http.ResponseWriter, r *http.Request) {
		path := strings.TrimPrefix(r.URL.Path, "/api/incidents/")
		parts := strings.Split(strings.Trim(path, "/"), "/")
		if len(parts) == 0 || parts[0] == "" {
			writeJSON(w, http.StatusNotFound, map[string]string{"error": "incident not found"})
			return
		}

		ctx, cancel := context.WithTimeout(r.Context(), 20*time.Second)
		defer cancel()

		incidentID := parts[0]
		if len(parts) >= 2 && parts[1] == "reasoning" {
			if len(parts) == 3 && parts[2] == "run" {
				if r.Method != http.MethodPost {
					writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "method not allowed"})
					return
				}
				request, err := store.CreateReasoningRequest(ctx, incidentID, "manual")
				if err != nil {
					writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
					return
				}
				writeJSON(w, http.StatusAccepted, request)
				return
			}
			if len(parts) == 3 && parts[2] == "retry" {
				if r.Method != http.MethodPost {
					writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "method not allowed"})
					return
				}
				request, err := store.CreateReasoningRequest(ctx, incidentID, "retry")
				if err != nil {
					writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
					return
				}
				writeJSON(w, http.StatusAccepted, request)
				return
			}
			if len(parts) == 3 && parts[2] == "history" && r.Method == http.MethodGet {
				history, err := store.ListReasoningRuns(ctx, incidentID, 20)
				if err != nil {
					writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
					return
				}
				writeJSON(w, http.StatusOK, history)
				return
			}
			if len(parts) == 4 && parts[2] == "runs" && r.Method == http.MethodGet {
				run, err := store.GetReasoningRun(ctx, incidentID, parts[3])
				if err != nil {
					writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
					return
				}
				writeJSON(w, http.StatusOK, run)
				return
			}
		}

		if len(parts) == 2 && parts[1] == "workflow" && r.Method == http.MethodPatch {
			var payload struct {
				Status string `json:"status"`
			}
			if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
				writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid payload"})
				return
			}
			update := incidents.WorkflowUpdate{
				Status: strings.ToLower(strings.TrimSpace(payload.Status)),
			}
			now := time.Now().UTC()
			switch update.Status {
			case "acknowledged":
				update.AcknowledgedAt = &now
			case "investigating":
				update.AcknowledgedAt = &now
				update.InvestigatingAt = &now
			case "resolved":
				update.ResolvedAt = &now
			}
			update.WorkflowUpdatedAt = &now
			item, err := store.UpdateWorkflow(ctx, incidentID, update)
			if err != nil {
				writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
				return
			}
			writeJSON(w, http.StatusOK, item)
			return
		}

		if len(parts) == 2 && parts[1] == "correlations" && r.Method == http.MethodGet {
			correlations, err := store.ListCorrelatedIncidents(ctx, incidentID, 24*time.Hour, 8)
			if err != nil {
				writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
				return
			}
			writeJSON(w, http.StatusOK, correlations)
			return
		}

		item, err := store.GetIncident(ctx, incidentID)
		if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
			return
		}
		if item == nil {
			writeJSON(w, http.StatusNotFound, map[string]string{"error": "incident not found"})
			return
		}

		if len(parts) == 2 && parts[1] == "timeline" {
			client, err := clickhouse.NewClient(ctx, chConfig)
			if err != nil {
				writeJSON(w, http.StatusBadGateway, map[string]string{"error": err.Error()})
				return
			}
			defer client.Close()
			timeline, err := client.BuildTimeline(ctx, clickhouse.Filters{
				Cluster:   item.Cluster,
				Namespace: item.Namespace,
				Service:   item.Service,
				Start:     item.Timestamp.Add(-5 * time.Minute),
				End:       item.Timestamp.Add(5 * time.Minute),
			}, item.Timestamp, 5*time.Minute)
			if err != nil {
				writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
				return
			}
			if len(timeline) == 0 {
				timeline = fallbackTimeline(*item)
			}
			writeJSON(w, http.StatusOK, map[string]any{
				"incident_id": item.ID,
				"events":      timeline,
			})
			return
		}

		if len(parts) == 2 && parts[1] == "evidence" && r.Method == http.MethodGet {
			fmt.Printf("api incident evidence incident=%s cluster=%q namespace=%q service=%q\n", item.ID, r.URL.Query().Get("cluster"), r.URL.Query().Get("namespace"), r.URL.Query().Get("service"))
			start, end := parseTimeRangeWithDefaults(r.URL.Query().Get("start"), r.URL.Query().Get("end"), 24*time.Hour)
			evidence := buildSelectedScopeEvidence(ctx, store, chConfig, project, item, clickhouse.Filters{
				Cluster:   firstNonEmpty(r.URL.Query().Get("cluster"), item.Cluster, item.Scope.Cluster),
				Namespace: firstNonEmpty(r.URL.Query().Get("namespace"), item.Namespace, item.Scope.Namespace),
				Service:   normalizeServiceName(firstNonEmpty(r.URL.Query().Get("service"), item.Service, item.Scope.Service)),
				Start:     start,
				End:       end,
			})
			writeJSON(w, http.StatusOK, evidence)
			return
		}

		writeJSON(w, http.StatusOK, item)
	})

	mux.HandleFunc("/api/topology", func(w http.ResponseWriter, r *http.Request) {
		ctx, cancel := context.WithTimeout(r.Context(), 60*time.Second)
		defer cancel()

		start, end := parseTimeRangeWithDefaults(r.URL.Query().Get("start"), r.URL.Query().Get("end"), 24*time.Hour)
		clusterFilter := firstNonEmpty(r.URL.Query().Get("cluster"), project.ClusterID)
		namespaceFilter := firstNonEmpty(r.URL.Query().Get("namespace"), project.NamespaceFilter)
		serviceFilter := normalizeServiceName(firstNonEmpty(r.URL.Query().Get("service"), project.ServiceFilter))
		logFilters("topology", clusterFilter, namespaceFilter, serviceFilter, r.URL.Query().Get("start"), r.URL.Query().Get("end"), r.URL.Query().Get("time_range"))
		client, err := clickhouse.NewClient(ctx, chConfig)
		cluster := clusterFilter
		namespace := namespaceFilter
		graph := emptyTopologyGraph()
		if err != nil {
			fmt.Printf("api topology client init failed: %v\n", err)
			if incidentGraph, incErr := buildGraphFromIncidentChainsFallback(r.Context(), store, project.ProjectID, clusterFilter, namespaceFilter, serviceFilter); incErr == nil {
				graph = dedupeGraph(sanitizeApplicationGraph(incidentGraph))
			} else {
				fmt.Printf("api topology client-init fallback failed: %v\n", incErr)
			}
		} else {
			defer client.Close()
			graph, err = client.BuildTopology(ctx, clickhouse.Filters{
				Cluster:   clusterFilter,
				Namespace: namespaceFilter,
				Service:   serviceFilter,
				Start:     start,
				End:       end,
			})
			if err != nil {
				fmt.Printf("api topology primary graph failed: %v\n", err)
				if incidentGraph, incErr := buildGraphFromIncidentChainsFallback(r.Context(), store, project.ProjectID, clusterFilter, namespaceFilter, serviceFilter); incErr == nil {
					graph = dedupeGraph(sanitizeApplicationGraph(incidentGraph))
				} else {
					fmt.Printf("api topology incident-chain fallback failed: %v\n", incErr)
					graph = emptyTopologyGraph()
				}
			} else {
				graph = dedupeGraph(graph)
				graph = sanitizeApplicationGraph(graph)
				if len(graph.Edges) == 0 && namespaceFilter != "" && serviceFilter == "" {
					scopedServiceSet := map[string]struct{}{}
					if scopedServices, svcErr := client.ListActiveServices(ctx, 6*time.Hour, clickhouse.ServiceSelection{
						Cluster:   clusterFilter,
						Namespace: namespaceFilter,
					}); svcErr == nil {
						for _, candidate := range scopedServices {
							if strings.TrimSpace(candidate.Service) == "" {
								continue
							}
							scopedServiceSet[candidate.Service] = struct{}{}
						}
					}
					if len(scopedServiceSet) == 0 {
						if scopedIncidents, incErr := store.ListIncidents(ctx, incidents.QueryFilters{
							ProjectID: project.ProjectID,
							Cluster:   clusterFilter,
							Namespace: namespaceFilter,
							Limit:     80,
						}); incErr == nil {
							for _, incident := range scopedIncidents {
								if strings.TrimSpace(incident.Service) == "" {
									continue
								}
								scopedServiceSet[incident.Service] = struct{}{}
							}
						}
					}
					if len(scopedServiceSet) > 0 {
						relaxedGraph, relaxedErr := client.BuildTopology(ctx, clickhouse.Filters{
							Cluster:   clusterFilter,
							Namespace: "",
							Service:   "",
							Start:     start,
							End:       end,
						})
						if relaxedErr == nil {
							serviceIDs := make([]string, 0, len(scopedServiceSet))
							for serviceID := range scopedServiceSet {
								serviceIDs = append(serviceIDs, serviceID)
							}
							graph = filterGraphByServiceSet(dedupeGraph(sanitizeApplicationGraph(relaxedGraph)), serviceIDs)
						}
					}
				}
				if len(graph.Edges) == 0 {
					if incidentGraph, incErr := buildGraphFromIncidentChainsFallback(r.Context(), store, project.ProjectID, clusterFilter, namespaceFilter, serviceFilter); incErr == nil {
						graph = dedupeGraph(sanitizeApplicationGraph(incidentGraph))
					} else {
						fmt.Printf("api topology empty graph fallback failed: %v\n", incErr)
					}
				}
			}
		}
		if serviceFilter != "" {
			graph = filterGraphByServiceChain(graph, serviceFilter)
		}
		graph = dedupeGraph(graph)
		if persistErr := store.UpsertDependencyGraph(ctx, cluster, namespace, graph); persistErr != nil {
			// keep API responsive even if persistence fails
		}
		if persistErr := store.ReplaceServiceDependencies(ctx, project.ProjectID, cluster, namespace, graph.Edges); persistErr != nil {
			// keep API responsive even if persistence fails
		}
		writeJSON(w, http.StatusOK, graph)
	})

	mux.HandleFunc("/api/filters", func(w http.ResponseWriter, r *http.Request) {
		ctx, cancel := context.WithTimeout(r.Context(), 20*time.Second)
		defer cancel()

		values := map[string][]string{
			"clusters":   []string{},
			"namespaces": []string{},
			"services":   []string{},
		}
		clusterSet := map[string]struct{}{}
		namespaceSet := map[string]struct{}{}
		serviceSet := map[string]struct{}{}

		if client, err := clickhouse.NewClient(ctx, chConfig); err == nil {
			defer client.Close()
			if services, svcErr := client.ListActiveServices(ctx, 6*time.Hour, clickhouse.ServiceSelection{
				Cluster:   project.ClusterID,
				Namespace: project.NamespaceFilter,
				Service:   project.ServiceFilter,
			}); svcErr == nil {
				for _, svc := range services {
					clusterSet[svc.Cluster] = struct{}{}
					if svc.Namespace != "" {
						namespaceSet[svc.Namespace] = struct{}{}
					}
					serviceSet[svc.Service] = struct{}{}
				}
			}
		}
		if incidentFilters, err := store.DistinctIncidentFilters(ctx); err == nil {
			if len(clusterSet) == 0 {
				for _, cluster := range incidentFilters["clusters"] {
					clusterSet[cluster] = struct{}{}
				}
			}
			if len(namespaceSet) == 0 {
				for _, namespace := range incidentFilters["namespaces"] {
					if strings.TrimSpace(namespace) != "" {
						namespaceSet[namespace] = struct{}{}
					}
				}
			}
			if len(incidentFilters["services"]) > 0 {
				incidentServices := map[string]struct{}{}
				for _, service := range incidentFilters["services"] {
					if strings.TrimSpace(service) == "" {
						continue
					}
					incidentServices[service] = struct{}{}
				}
				serviceSet = incidentServices
			}
		}
		values["clusters"] = sortedNonEmptyKeys(clusterSet)
		values["namespaces"] = sortedNonEmptyKeys(namespaceSet)
		filteredServices := map[string]struct{}{}
		for service := range serviceSet {
			if strings.TrimSpace(service) == "" {
				continue
			}
			if clickhouse.IsIgnoredService(service) {
				continue
			}
			filteredServices[service] = struct{}{}
		}
		values["services"] = sortedNonEmptyKeys(filteredServices)
		writeJSON(w, http.StatusOK, values)
	})

	mux.HandleFunc("/api/problems", func(w http.ResponseWriter, r *http.Request) {
		ctx, cancel := context.WithTimeout(r.Context(), 20*time.Second)
		defer cancel()
		clusterFilter := firstNonEmpty(r.URL.Query().Get("cluster"), project.ClusterID)
		namespaceFilter := firstNonEmpty(r.URL.Query().Get("namespace"), project.NamespaceFilter)
		serviceFilter := normalizeServiceName(firstNonEmpty(r.URL.Query().Get("service"), project.ServiceFilter))
		logFilters("problems", clusterFilter, namespaceFilter, serviceFilter, r.URL.Query().Get("start"), r.URL.Query().Get("end"), r.URL.Query().Get("time_range"))
		problems, err := store.ListProblems(
			ctx,
			firstNonEmpty(r.URL.Query().Get("project_id"), project.ProjectID),
			clusterFilter,
			namespaceFilter,
			serviceFilter,
			parseLimit(r.URL.Query().Get("limit"), 100),
		)
		if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
			return
		}
		writeJSON(w, http.StatusOK, problems)
	})

	mux.HandleFunc("/api/service-health", func(w http.ResponseWriter, r *http.Request) {
		ctx, cancel := context.WithTimeout(r.Context(), 20*time.Second)
		defer cancel()
		clusterFilter := firstNonEmpty(r.URL.Query().Get("cluster"), project.ClusterID)
		namespaceFilter := firstNonEmpty(r.URL.Query().Get("namespace"), project.NamespaceFilter)
		serviceFilter := normalizeServiceName(firstNonEmpty(r.URL.Query().Get("service"), project.ServiceFilter))
		logFilters("service-health", clusterFilter, namespaceFilter, serviceFilter, r.URL.Query().Get("start"), r.URL.Query().Get("end"), r.URL.Query().Get("time_range"))
		items, err := store.ListServiceHealth(
			ctx,
			firstNonEmpty(r.URL.Query().Get("project_id"), project.ProjectID),
			clusterFilter,
			namespaceFilter,
			serviceFilter,
			parseLimit(r.URL.Query().Get("limit"), 200),
		)
		if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
			return
		}
		writeJSON(w, http.StatusOK, items)
	})

	mux.HandleFunc("/api/cluster-report", func(w http.ResponseWriter, r *http.Request) {
		ctx, cancel := context.WithTimeout(r.Context(), 20*time.Second)
		defer cancel()
		clusterID := resolveClusterID(ctx, store, firstNonEmpty(r.URL.Query().Get("cluster_id"), r.URL.Query().Get("cluster"), project.ClusterID))
		report, err := store.BuildClusterReport(
			ctx,
			firstNonEmpty(r.URL.Query().Get("project_id"), project.ProjectID),
			clusterID,
		)
		if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
			return
		}
		writeJSON(w, http.StatusOK, report)
	})

	mux.HandleFunc("/api/changes", func(w http.ResponseWriter, r *http.Request) {
		ctx, cancel := context.WithTimeout(r.Context(), 20*time.Second)
		defer cancel()
		clusterID := resolveClusterID(ctx, store, firstNonEmpty(r.URL.Query().Get("cluster_id"), r.URL.Query().Get("cluster"), project.ClusterID))
		namespace := firstNonEmpty(r.URL.Query().Get("namespace"), project.NamespaceFilter)
		limit := parseLimit(r.URL.Query().Get("limit"), 200)

		if client, err := clickhouse.NewClient(ctx, chConfig); err == nil {
			defer client.Close()
			if detected, detectErr := client.DetectSystemChanges(ctx, clusterID, namespace, 24*time.Hour, limit); detectErr == nil {
				for _, change := range detected {
					_ = store.UpsertSystemChange(ctx, incidents.SystemChange{
						ChangeID:     "ch:" + change.Timestamp.Format(time.RFC3339Nano) + ":" + change.ChangeType + ":" + change.ResourceName,
						ClusterID:    change.ClusterID,
						Namespace:    change.Namespace,
						ResourceType: change.ResourceType,
						ResourceName: change.ResourceName,
						ChangeType:   change.ChangeType,
						Timestamp:    change.Timestamp,
						Metadata: map[string]any{
							"body": change.Metadata["body"],
						},
					})
				}
			}
		}
		items, err := store.ListSystemChanges(ctx, clusterID, namespace, limit)
		if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
			return
		}
		writeJSON(w, http.StatusOK, items)
	})

	mux.HandleFunc("/api/slo-status", func(w http.ResponseWriter, r *http.Request) {
		ctx, cancel := context.WithTimeout(r.Context(), 20*time.Second)
		defer cancel()
		items, err := sloEngine.Status(
			ctx,
			firstNonEmpty(r.URL.Query().Get("project_id"), project.ProjectID),
			firstNonEmpty(r.URL.Query().Get("cluster"), project.ClusterID),
			firstNonEmpty(r.URL.Query().Get("namespace"), project.NamespaceFilter),
			parseLimit(r.URL.Query().Get("limit"), 300),
		)
		if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
			return
		}
		writeJSON(w, http.StatusOK, items)
	})

	mux.HandleFunc("/api/runbooks", func(w http.ResponseWriter, r *http.Request) {
		ctx, cancel := context.WithTimeout(r.Context(), 20*time.Second)
		defer cancel()
		items, err := store.ListRunbooks(
			ctx,
			r.URL.Query().Get("incident_type"),
			r.URL.Query().Get("root_cause_signal"),
			parseLimit(r.URL.Query().Get("limit"), 100),
		)
		if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
			return
		}
		writeJSON(w, http.StatusOK, items)
	})

	mux.HandleFunc("/api/observability-report", func(w http.ResponseWriter, r *http.Request) {
		ctx, cancel := context.WithTimeout(r.Context(), 20*time.Second)
		defer cancel()
		clusterID := resolveClusterID(ctx, store, firstNonEmpty(r.URL.Query().Get("cluster_id"), r.URL.Query().Get("cluster"), project.ClusterID))
		report, err := coverageEngine.Report(
			ctx,
			firstNonEmpty(r.URL.Query().Get("project_id"), project.ProjectID),
			clusterID,
		)
		if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
			return
		}
		writeJSON(w, http.StatusOK, report)
	})

	return withCORS(mux)
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if strings.TrimSpace(value) != "" {
			return value
		}
	}
	return ""
}

func resolveClusterID(ctx context.Context, store *incidents.Store, preferred string) string {
	if value := strings.TrimSpace(preferred); value != "" {
		return value
	}
	if filters, err := store.DistinctFilters(ctx); err == nil {
		clusters := filters["clusters"]
		if len(clusters) > 0 {
			return clusters[0]
		}
	}
	return ""
}

func sortedKeys(values map[string]struct{}) []string {
	items := make([]string, 0, len(values))
	for value := range values {
		items = append(items, value)
	}
	sort.Strings(items)
	return items
}

func sortedNonEmptyKeys(values map[string]struct{}) []string {
	items := make([]string, 0, len(values))
	for value := range values {
		if strings.TrimSpace(value) == "" {
			continue
		}
		items = append(items, value)
	}
	sort.Strings(items)
	return items
}

func withCORS(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		origin := r.Header.Get("Origin")
		if origin == "http://localhost:3000" {
			w.Header().Set("Access-Control-Allow-Origin", origin)
		} else {
			w.Header().Set("Access-Control-Allow-Origin", "*")
		}
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, PATCH, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization")
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}

func parseLimit(raw string, fallback int) int {
	if raw == "" {
		return fallback
	}
	parsed, err := strconv.Atoi(raw)
	if err != nil || parsed <= 0 || parsed > 500 {
		return fallback
	}
	return parsed
}

func parseOptionalTime(raw string) *time.Time {
	if raw == "" {
		return nil
	}
	parsed, err := time.Parse(time.RFC3339, raw)
	if err != nil {
		return nil
	}
	utc := parsed.UTC()
	return &utc
}

func parseTimeRangeWithDefaults(startRaw, endRaw string, fallbackWindow time.Duration) (time.Time, time.Time) {
	end := time.Now().UTC()
	start := end.Add(-fallbackWindow)
	if parsed := parseOptionalTime(startRaw); parsed != nil {
		start = *parsed
	}
	if parsed := parseOptionalTime(endRaw); parsed != nil {
		end = *parsed
	}
	return start, end
}

func fallbackTimeline(item incidents.Incident) []clickhouse.TimelineEvent {
	events := make([]clickhouse.TimelineEvent, 0, len(item.TelemetrySnapshot.ErrorLogs)+len(item.TelemetrySnapshot.MetricHighlights))
	for _, entry := range item.TelemetrySnapshot.ErrorLogs {
		events = append(events, clickhouse.TimelineEvent{
			Timestamp: item.Timestamp,
			Kind:      "log",
			Severity:  "medium",
			Entity:    item.Service,
			Title:     "Observed log anomaly",
			Details:   entry,
		})
	}
	for metric, value := range item.TelemetrySnapshot.MetricHighlights {
		events = append(events, clickhouse.TimelineEvent{
			Timestamp: item.Timestamp,
			Kind:      "metric",
			Severity:  "info",
			Entity:    item.Service,
			Title:     metric,
			Details:   "Captured during anomaly detection",
			Value:     value,
		})
	}
	return events
}

func normalizeDependencyType(value string) string {
	switch value {
	case "trace_parent_child", "http":
		return "trace_http"
	case "kubernetes":
		return "kubernetes_dns"
	default:
		return value
	}
}

func dedupeGraph(graph clickhouse.TopologyGraph) clickhouse.TopologyGraph {
	nodeSet := map[string]struct{}{}
	nodes := make([]clickhouse.TopologyNode, 0, len(graph.Nodes))
	for _, node := range graph.Nodes {
		key := node.ID
		if _, exists := nodeSet[key]; exists {
			continue
		}
		nodeSet[key] = struct{}{}
		nodes = append(nodes, node)
	}
	edgeSet := map[string]struct{}{}
	edges := make([]clickhouse.TopologyEdge, 0, len(graph.Edges))
	for _, edge := range graph.Edges {
		key := edge.Source + "|" + edge.Target + "|" + edge.DependencyType
		if _, exists := edgeSet[key]; exists {
			continue
		}
		edgeSet[key] = struct{}{}
		edges = append(edges, edge)
	}
	graph.Nodes = nodes
	graph.Edges = edges
	return graph
}

func sanitizeApplicationGraph(graph clickhouse.TopologyGraph) clickhouse.TopologyGraph {
	infraAliasSet := map[string]struct{}{}
	for _, node := range graph.Nodes {
		id := strings.TrimSpace(node.ID)
		if id == "" {
			continue
		}
		nodeType := strings.ToLower(strings.TrimSpace(node.NodeType))
		if nodeType == "" {
			nodeType = inferNodeTypeFromID(id)
		}
		switch nodeType {
		case "database":
			if alias := infraSystemAlias(id, "db:"); alias != "" {
				infraAliasSet[alias] = struct{}{}
			}
		case "messaging":
			if alias := infraSystemAlias(id, "messaging:"); alias != "" {
				infraAliasSet[alias] = struct{}{}
			}
		}
	}
	keepNodes := make([]clickhouse.TopologyNode, 0, len(graph.Nodes))
	allowed := map[string]clickhouse.TopologyNode{}
	for _, node := range graph.Nodes {
		id := strings.TrimSpace(node.ID)
		if id == "" {
			continue
		}
		nodeType := strings.ToLower(strings.TrimSpace(node.NodeType))
		if nodeType == "" {
			nodeType = inferNodeTypeFromID(id)
		}
		node.NodeType = nodeType
		if nodeType == "service" {
			normalizedID := normalizeServiceName(id)
			if normalizedID == "" || !serviceNodePattern.MatchString(normalizedID) || clickhouse.IsIgnoredService(normalizedID) {
				continue
			}
			if _, aliasConflict := infraAliasSet[normalizedID]; aliasConflict {
				continue
			}
			node.ID = normalizedID
			node.Label = normalizedID
			allowed[normalizedID] = node
			keepNodes = append(keepNodes, node)
			continue
		}
		if nodeType != "database" && nodeType != "messaging" {
			continue
		}
		allowed[id] = node
		keepNodes = append(keepNodes, node)
	}
	keepEdges := make([]clickhouse.TopologyEdge, 0, len(graph.Edges))
	for _, edge := range graph.Edges {
		source := strings.TrimSpace(edge.Source)
		target := strings.TrimSpace(edge.Target)
		if source == "" || target == "" {
			continue
		}
		if inferNodeTypeFromID(source) == "service" {
			source = normalizeServiceName(source)
			if source == "" || !serviceNodePattern.MatchString(source) {
				continue
			}
		}
		if inferNodeTypeFromID(target) == "service" {
			target = normalizeServiceName(target)
			if target == "" || !serviceNodePattern.MatchString(target) {
				continue
			}
		}
		edge.Source = source
		edge.Target = target
		if _, ok := allowed[source]; !ok {
			continue
		}
		if _, ok := allowed[target]; !ok {
			continue
		}
		keepEdges = append(keepEdges, edge)
	}
	graph.Nodes = keepNodes
	graph.Edges = keepEdges
	return graph
}

func infraSystemAlias(id, prefix string) string {
	value := strings.TrimSpace(strings.TrimPrefix(strings.ToLower(id), prefix))
	if value == "" {
		return ""
	}
	parts := strings.SplitN(value, "/", 2)
	return normalizeServiceName(parts[0])
}

func normalizeServiceName(value string) string {
	service := strings.ToLower(strings.TrimSpace(value))
	if service == "" {
		return ""
	}
	for _, suffix := range []string{".svc.cluster.local", ".svc", ".cluster.local", ".local"} {
		service = strings.TrimSuffix(service, suffix)
	}
	return strings.Trim(service, "-._")
}

func inferNodeTypeFromID(id string) string {
	return clickhouse.InferTopologyNodeType(id)
}

func logFilters(endpoint, cluster, namespace, service, start, end, timeRange string) {
	fmt.Printf("api %s filters cluster=%q namespace=%q service=%q start=%q end=%q time_range=%q\n", endpoint, cluster, namespace, service, start, end, timeRange)
}

func filterGraphByServiceChain(graph clickhouse.TopologyGraph, service string) clickhouse.TopologyGraph {
	target := normalizeServiceName(service)
	if target == "" {
		return graph
	}
	return filterGraphByServiceSet(graph, []string{target})
}

func filterGraphByServiceSet(graph clickhouse.TopologyGraph, services []string) clickhouse.TopologyGraph {
	targetSet := map[string]struct{}{}
	for _, service := range services {
		target := normalizeServiceName(service)
		if target != "" {
			targetSet[target] = struct{}{}
		}
	}
	if len(targetSet) == 0 {
		return graph
	}
	seen := map[string]struct{}{}
	edges := make([]clickhouse.TopologyEdge, 0, len(graph.Edges))
	for _, edge := range graph.Edges {
		_, sourceTargeted := targetSet[normalizeServiceName(edge.Source)]
		_, targetTargeted := targetSet[normalizeServiceName(edge.Target)]
		if !sourceTargeted && !targetTargeted {
			continue
		}
		edges = append(edges, edge)
		seen[edge.Source] = struct{}{}
		seen[edge.Target] = struct{}{}
	}
	for service := range targetSet {
		seen[service] = struct{}{}
	}
	if len(edges) == 0 && len(seen) == 0 {
		return clickhouse.TopologyGraph{GeneratedAt: graph.GeneratedAt, Nodes: []clickhouse.TopologyNode{}, Edges: []clickhouse.TopologyEdge{}}
	}
	nodes := make([]clickhouse.TopologyNode, 0, len(graph.Nodes))
	for _, node := range graph.Nodes {
		if _, ok := seen[node.ID]; ok {
			nodes = append(nodes, node)
		}
	}
	graph.Nodes = nodes
	graph.Edges = edges
	return graph
}

func buildGraphFromIncidentChains(ctx context.Context, store *incidents.Store, projectID, cluster, namespace, service string) (clickhouse.TopologyGraph, error) {
	items, err := store.ListIncidents(ctx, incidents.QueryFilters{
		ProjectID: projectID,
		Cluster:   cluster,
		Namespace: namespace,
		Service:   service,
		Limit:     400,
	})
	if err != nil {
		return clickhouse.TopologyGraph{}, err
	}
	graph := clickhouse.TopologyGraph{
		GeneratedAt: time.Now().UTC(),
		Nodes:       []clickhouse.TopologyNode{},
		Edges:       []clickhouse.TopologyEdge{},
	}
	nodeSet := map[string]clickhouse.TopologyNode{}
	edgeSet := map[string]struct{}{}
	for _, incident := range items {
		incidentService := canonicalNodeID(incident.Service)
		if incidentService == "" {
			incidentService = canonicalNodeID(incident.RootCauseEntity)
		}
		for _, chain := range incident.DependencyChain {
			parts := splitChainParts(chain)
			if len(parts) < 2 {
				continue
			}
			for idx := 0; idx < len(parts)-1; idx++ {
				source := strings.TrimSpace(parts[idx])
				target := strings.TrimSpace(parts[idx+1])
				if source == "" || target == "" {
					continue
				}
				sourceNode := canonicalNodeID(source)
				targetNode := canonicalNodeID(target)
				if sourceNode == "" || targetNode == "" {
					continue
				}
				key := sourceNode + "|" + targetNode
				if _, exists := edgeSet[key]; !exists {
					graph.Edges = append(graph.Edges, clickhouse.TopologyEdge{
						Source:         sourceNode,
						Target:         targetNode,
						DependencyType: inferDependencyType(sourceNode, targetNode),
						CallCount:      1,
					})
					edgeSet[key] = struct{}{}
				}
				if _, ok := nodeSet[sourceNode]; !ok {
					nodeSet[sourceNode] = clickhouse.TopologyNode{
						ID:        sourceNode,
						Label:     sourceNode,
						NodeType:  inferNodeTypeFromID(sourceNode),
						Cluster:   incident.Cluster,
						Namespace: incident.Namespace,
					}
				}
				if _, ok := nodeSet[targetNode]; !ok {
					nodeSet[targetNode] = clickhouse.TopologyNode{
						ID:        targetNode,
						Label:     targetNode,
						NodeType:  inferNodeTypeFromID(targetNode),
						Cluster:   incident.Cluster,
						Namespace: incident.Namespace,
					}
				}
			}
		}
		if incidentService == "" || len(incident.Impacts) == 0 {
			continue
		}
		if _, ok := nodeSet[incidentService]; !ok {
			nodeSet[incidentService] = clickhouse.TopologyNode{
				ID:        incidentService,
				Label:     incidentService,
				NodeType:  inferNodeTypeFromID(incidentService),
				Cluster:   incident.Cluster,
				Namespace: incident.Namespace,
			}
		}
		for _, impact := range incident.Impacts {
			targetNode := canonicalNodeID(impact.Service)
			if targetNode == "" || targetNode == incidentService {
				continue
			}
			key := incidentService + "|" + targetNode
			if _, exists := edgeSet[key]; !exists {
				graph.Edges = append(graph.Edges, clickhouse.TopologyEdge{
					Source:         incidentService,
					Target:         targetNode,
					DependencyType: inferDependencyType(incidentService, targetNode),
					CallCount:      1,
				})
				edgeSet[key] = struct{}{}
			}
			if _, ok := nodeSet[targetNode]; !ok {
				nodeSet[targetNode] = clickhouse.TopologyNode{
					ID:        targetNode,
					Label:     targetNode,
					NodeType:  inferNodeTypeFromID(targetNode),
					Cluster:   incident.Cluster,
					Namespace: incident.Namespace,
				}
			}
		}
	}
	for _, node := range nodeSet {
		graph.Nodes = append(graph.Nodes, node)
	}
	return graph, nil
}

func buildGraphFromIncidentChainsFallback(parent context.Context, store *incidents.Store, projectID, cluster, namespace, service string) (clickhouse.TopologyGraph, error) {
	fallbackCtx, cancel := context.WithTimeout(parent, 5*time.Second)
	defer cancel()
	return buildGraphFromIncidentChains(fallbackCtx, store, projectID, cluster, namespace, service)
}

func emptyTopologyGraph() clickhouse.TopologyGraph {
	return clickhouse.TopologyGraph{
		GeneratedAt: time.Now().UTC(),
		Nodes:       []clickhouse.TopologyNode{},
		Edges:       []clickhouse.TopologyEdge{},
	}
}

func splitChainParts(value string) []string {
	segments := strings.Split(value, "->")
	parts := make([]string, 0, len(segments))
	for _, segment := range segments {
		item := strings.TrimSpace(segment)
		if item == "" {
			continue
		}
		parts = append(parts, item)
	}
	return parts
}

func canonicalNodeID(value string) string {
	nodeID := clickhouse.CanonicalTopologyNodeID(value)
	if nodeID == "" {
		return ""
	}
	if strings.ContainsAny(nodeID, " \t\r\n") || len(nodeID) > 128 || !structuredTopologyNodePattern.MatchString(nodeID) {
		return ""
	}
	if clickhouse.InferTopologyNodeType(nodeID) == "service" {
		normalized := normalizeServiceName(nodeID)
		if normalized == "" || !serviceNodePattern.MatchString(normalized) {
			return ""
		}
		return normalized
	}
	return nodeID
}

func inferDependencyType(source, target string) string {
	if inferNodeTypeFromID(source) == "messaging" || inferNodeTypeFromID(target) == "messaging" {
		return "messaging"
	}
	if inferNodeTypeFromID(target) == "database" {
		return "database"
	}
	return "trace_http"
}

func resolveClusterFromKubeContext(ctx context.Context) string {
	cmd := kubectlCommand(ctx, "config", "current-context")
	output, err := cmd.Output()
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(output))
}

func kubernetesNamespaces(ctx context.Context) ([]string, error) {
	cmd := kubectlCommand(ctx, "get", "ns", "-o", "json")
	output, err := cmd.Output()
	if err != nil {
		return nil, err
	}
	var payload struct {
		Items []struct {
			Metadata struct {
				Name string `json:"name"`
			} `json:"metadata"`
		} `json:"items"`
	}
	if err := json.Unmarshal(output, &payload); err != nil {
		return nil, err
	}
	namespaces := make([]string, 0, len(payload.Items))
	for _, item := range payload.Items {
		name := strings.TrimSpace(item.Metadata.Name)
		if name == "" {
			continue
		}
		namespaces = append(namespaces, name)
	}
	sort.Strings(namespaces)
	return namespaces, nil
}

func kubectlCommand(ctx context.Context, args ...string) *exec.Cmd {
	if _, err := os.Stat("/tmp/kubeconfig"); err == nil {
		full := append([]string{"--kubeconfig", "/tmp/kubeconfig"}, args...)
		return exec.CommandContext(ctx, "kubectl", full...)
	}
	return exec.CommandContext(ctx, "kubectl", args...)
}
