package truth

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"sort"
	"strconv"
	"strings"
	"time"

	"deep-observer/ai-core/internal/clickhouse"
)

type signozServiceItem struct {
	ServiceName string  `json:"serviceName"`
	Percentile99 float64 `json:"p99"`
	AvgDuration  float64 `json:"avgDuration"`
	NumCalls     uint64  `json:"numCalls"`
	CallRate     float64 `json:"callRate"`
	NumErrors    uint64  `json:"numErrors"`
	ErrorRate    float64 `json:"errorRate"`
}

type signozDependencyItem struct {
	Parent    string  `json:"parent"`
	Child     string  `json:"child"`
	CallCount uint64  `json:"callCount"`
	ErrorRate float64 `json:"errorRate"`
	P99       float64 `json:"p99"`
	P95       float64 `json:"p95"`
	P90       float64 `json:"p90"`
	P75       float64 `json:"p75"`
	P50       float64 `json:"p50"`
}

type signozEvidenceSummary struct {
	RequestCount    int64
	LogCount        int64
	TraceCount      int
	ErrorLogSamples []string
	TraceIDs        []string
	MetricHighlights map[string]float64
	ErrorRate       float64
	P95LatencyMs    float64
}

func signozBaseURL() string {
	for _, key := range []string{"SIGNOZ_API_BASE_URL", "SIGNOZ_BASE_URL"} {
		if value := strings.TrimSpace(os.Getenv(key)); value != "" {
			return strings.TrimRight(value, "/")
		}
	}
	return "http://signoz:8080"
}

func signozAPIKey() string {
	for _, key := range []string{"SIGNOZ_API_KEY", "signoz_api_key"} {
		if value := strings.TrimSpace(os.Getenv(key)); value != "" {
			return value
		}
	}
	return ""
}

func (s *Service) signozRequest(ctx context.Context, method, path string, payload any, out any) error {
	var bodyReader io.Reader
	if payload != nil {
		encoded, err := json.Marshal(payload)
		if err != nil {
			return err
		}
		bodyReader = bytes.NewReader(encoded)
	}

	req, err := http.NewRequestWithContext(ctx, method, signozBaseURL()+path, bodyReader)
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	if key := signozAPIKey(); key != "" {
		req.Header.Set("Authorization", "Bearer "+key)
		req.Header.Set("SIGNOZ-API-KEY", key)
	}

	client := &http.Client{Timeout: 12 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	raw, err := io.ReadAll(io.LimitReader(resp.Body, 8<<20))
	if err != nil {
		return err
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("signoz request failed status=%d path=%s body=%s", resp.StatusCode, path, strings.TrimSpace(string(raw)))
	}
	if len(raw) == 0 || out == nil {
		return nil
	}
	if err := json.Unmarshal(raw, out); err == nil {
		return nil
	}

	// Some SigNoz surfaces wrap payload as {"status":"success","data":...}
	var envelope map[string]any
	if err := json.Unmarshal(raw, &envelope); err != nil {
		return err
	}
	data, ok := envelope["data"]
	if !ok {
		return fmt.Errorf("signoz response shape unsupported for path %s", path)
	}
	encodedData, err := json.Marshal(data)
	if err != nil {
		return err
	}
	return json.Unmarshal(encodedData, out)
}

func (s *Service) signozTags(scope NormalizedScope, includeService bool) []map[string]any {
	tags := []map[string]any{}
	add := func(key, value string) {
		value = strings.TrimSpace(value)
		if value == "" {
			return
		}
		tags = append(tags, map[string]any{
			"key":          key,
			"operator":     "Equals",
			"stringValues": []string{value},
			"numberValues": []float64{},
			"boolValues":   []bool{},
			"tagType":      "ResourceAttribute",
		})
	}
	if includeService {
		add("service.name", scope.Service)
	}
	return tags
}

func (s *Service) signozFetchServices(ctx context.Context, scope NormalizedScope) ([]signozServiceItem, error) {
	payload := map[string]any{
		"start": strconv.FormatInt(scope.Start.UTC().UnixNano(), 10),
		"end":   strconv.FormatInt(scope.End.UTC().UnixNano(), 10),
		"tags":  s.signozTags(scope, false),
	}
	services := []signozServiceItem{}
	if err := s.signozRequest(ctx, http.MethodPost, "/api/v1/services", payload, &services); err != nil {
		return nil, err
	}
	out := make([]signozServiceItem, 0, len(services))
	for _, item := range services {
		item.ServiceName = normalizeServiceName(item.ServiceName)
		if item.ServiceName == "" {
			continue
		}
		if scope.Service != "" && item.ServiceName != normalizeServiceName(scope.Service) {
			continue
		}
		out = append(out, item)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ServiceName < out[j].ServiceName })
	return out, nil
}

func (s *Service) signozFetchDependencyGraph(ctx context.Context, scope NormalizedScope) (clickhouse.TopologyGraph, error) {
	payload := map[string]any{
		"start": strconv.FormatInt(scope.Start.UTC().UnixNano(), 10),
		"end":   strconv.FormatInt(scope.End.UTC().UnixNano(), 10),
		"tags":  s.signozTags(scope, false),
	}
	items := []signozDependencyItem{}
	if err := s.signozRequest(ctx, http.MethodPost, "/api/v1/dependency_graph", payload, &items); err != nil {
		return clickhouse.TopologyGraph{Nodes: []clickhouse.TopologyNode{}, Edges: []clickhouse.TopologyEdge{}}, err
	}
	nodeMap := map[string]clickhouse.TopologyNode{}
	edges := make([]clickhouse.TopologyEdge, 0, len(items))
	for _, item := range items {
		source := clickhouse.CanonicalTopologyNodeID(item.Parent)
		target := clickhouse.CanonicalTopologyNodeID(item.Child)
		if source == "" || target == "" || source == target {
			continue
		}
		edge := clickhouse.TopologyEdge{
			Source:         source,
			Target:         target,
			DependencyType: inferSynapseDependencyType(source, target),
			CallCount:      int64(item.CallCount),
			AvgLatencyMs:   firstPositiveFloat(item.P95, item.P99, item.P90, item.P75, item.P50),
			ErrorRate:      item.ErrorRate,
		}
		edges = append(edges, edge)
		if _, ok := nodeMap[source]; !ok {
			nodeMap[source] = clickhouse.TopologyNode{
				ID:        source,
				Label:     source,
				NodeType:  clickhouse.InferTopologyNodeType(source),
				Cluster:   scope.Cluster,
				Namespace: scope.Namespace,
			}
		}
		if _, ok := nodeMap[target]; !ok {
			nodeMap[target] = clickhouse.TopologyNode{
				ID:        target,
				Label:     target,
				NodeType:  clickhouse.InferTopologyNodeType(target),
				Cluster:   scope.Cluster,
				Namespace: scope.Namespace,
			}
		}
	}
	nodes := make([]clickhouse.TopologyNode, 0, len(nodeMap))
	for _, node := range nodeMap {
		nodes = append(nodes, node)
	}
	graph := clickhouse.TopologyGraph{
		GeneratedAt: time.Now().UTC(),
		Nodes:       nodes,
		Edges:       edges,
	}
	return dedupeGraph(sanitizeGraph(graph)), nil
}

func inferSynapseDependencyType(source, target string) string {
	sourceType := clickhouse.InferTopologyNodeType(source)
	targetType := clickhouse.InferTopologyNodeType(target)
	if sourceType == "messaging" || targetType == "messaging" {
		return "messaging"
	}
	if targetType == "database" {
		return "database"
	}
	return "trace_http"
}

func firstPositiveFloat(values ...float64) float64 {
	for _, value := range values {
		if value > 0 {
			return value
		}
	}
	return 0
}

func (s *Service) signozQueryRange(ctx context.Context, payload map[string]any) (map[string]any, error) {
	response := map[string]any{}
	if err := s.signozRequest(ctx, http.MethodPost, "/api/v5/query_range", payload, &response); err != nil {
		return nil, err
	}
	return response, nil
}

func (s *Service) scopeFilterExpression(scope NormalizedScope) string {
	filters := []string{}
	if scope.Service != "" {
		filters = append(filters, fmt.Sprintf("service.name = %s", quoteFilterValue(scope.Service)))
	}
	return strings.Join(filters, " AND ")
}

func quoteFilterValue(value string) string {
	escaped := strings.ReplaceAll(strings.TrimSpace(value), "'", "\\'")
	return "'" + escaped + "'"
}

func (s *Service) signozCountScalar(ctx context.Context, scope NormalizedScope, signal string, extraFilter string) (int64, error) {
	filterExpr := s.scopeFilterExpression(scope)
	if extraFilter != "" {
		if filterExpr != "" {
			filterExpr = "(" + filterExpr + ") AND (" + extraFilter + ")"
		} else {
			filterExpr = extraFilter
		}
	}
	spec := map[string]any{
		"name":   "A",
		"signal": signal,
		"aggregations": []map[string]any{
			{"expression": "count()", "alias": "count"},
		},
	}
	if strings.TrimSpace(filterExpr) != "" {
		spec["filter"] = map[string]any{"expression": filterExpr}
	}
	payload := map[string]any{
		"schemaVersion": "v1",
		"start":         uint64(scope.Start.UTC().UnixMilli()),
		"end":           uint64(scope.End.UTC().UnixMilli()),
		"requestType":   "scalar",
		"compositeQuery": map[string]any{
			"queries": []map[string]any{
				{"type": "builder_query", "spec": spec},
			},
		},
	}
	resp, err := s.signozQueryRange(ctx, payload)
	if err != nil {
		encodedPayload, _ := json.Marshal(payload)
		log.Printf("truth: signoz scalar request failed signal=%s payload=%s err=%v", signal, string(encodedPayload), err)
		return 0, err
	}
	return extractScalarCount(resp), nil
}

func (s *Service) signozFetchScopeFacets(ctx context.Context, scope NormalizedScope) ([]string, []string, []string, error) {
	signals := []string{"traces", "logs"}
	clusterSet := map[string]struct{}{}
	namespaceSet := map[string]struct{}{}
	serviceSet := map[string]struct{}{}
	var firstErr error

	for _, signal := range signals {
		payload := s.signozGroupedFacetPayload(scope, signal)
		resp, err := s.signozQueryRange(ctx, payload)
		if err != nil {
			if firstErr == nil {
				firstErr = err
			}
			continue
		}
		rows := extractScalarRows(resp)
		for _, row := range rows {
			service := normalizeServiceName(fmt.Sprintf("%v", row["service.name"]))
			namespace := strings.TrimSpace(fmt.Sprintf("%v", row["k8s.namespace.name"]))
			cluster := strings.TrimSpace(fmt.Sprintf("%v", row["k8s.cluster.name"]))
			if service != "" && service != "<nil>" {
				serviceSet[service] = struct{}{}
			}
			if namespace != "" && namespace != "<nil>" {
				namespaceSet[namespace] = struct{}{}
			}
			if cluster != "" && cluster != "<nil>" {
				clusterSet[cluster] = struct{}{}
			}
		}
	}

	return sortedSet(clusterSet), sortedSet(namespaceSet), sortedSet(serviceSet), firstErr
}

func (s *Service) signozGroupedFacetPayload(scope NormalizedScope, signal string) map[string]any {
	filterExpr := s.scopeFilterExpression(scope)
	spec := map[string]any{
		"name":   "A",
		"signal": signal,
		"aggregations": []map[string]any{
			{"expression": "count()", "alias": "count"},
		},
		"groupBy": []map[string]any{
			{"name": "service.name", "fieldContext": "resource"},
			{"name": "k8s.namespace.name", "fieldContext": "resource"},
			{"name": "k8s.cluster.name", "fieldContext": "resource"},
		},
		"limit": 500,
	}
	if filterExpr != "" {
		spec["filter"] = map[string]any{"expression": filterExpr}
	}
	return map[string]any{
		"schemaVersion": "v1",
		"start":         uint64(scope.Start.UTC().UnixMilli()),
		"end":           uint64(scope.End.UTC().UnixMilli()),
		"requestType":   "scalar",
		"compositeQuery": map[string]any{
			"queries": []map[string]any{
				{"type": "builder_query", "spec": spec},
			},
		},
	}
}

func extractScalarRows(response map[string]any) []map[string]any {
	rowsOut := []map[string]any{}
	data, _ := response["data"].(map[string]any)
	results, _ := data["results"].([]any)
	for _, result := range results {
		item, ok := result.(map[string]any)
		if !ok {
			continue
		}
		columnsRaw, _ := item["columns"].([]any)
		columnNames := []string{}
		for _, col := range columnsRaw {
			descriptor, ok := col.(map[string]any)
			if !ok {
				columnNames = append(columnNames, "")
				continue
			}
			name := strings.TrimSpace(fmt.Sprintf("%v", descriptor["name"]))
			columnNames = append(columnNames, name)
		}
		dataRows, _ := item["data"].([]any)
		for _, row := range dataRows {
			values, ok := row.([]any)
			if !ok {
				continue
			}
			entry := map[string]any{}
			for index := range values {
				if index < len(columnNames) && columnNames[index] != "" {
					entry[columnNames[index]] = values[index]
				}
			}
			rowsOut = append(rowsOut, entry)
		}
	}
	return rowsOut
}

func extractScalarCount(response map[string]any) int64 {
	data, _ := response["data"].(map[string]any)
	results, _ := data["results"].([]any)
	for _, result := range results {
		item, ok := result.(map[string]any)
		if !ok {
			continue
		}
		rows, _ := item["data"].([]any)
		for _, row := range rows {
			values, ok := row.([]any)
			if !ok || len(values) == 0 {
				continue
			}
			for i := len(values) - 1; i >= 0; i-- {
				if value, ok := toInt64(values[i]); ok {
					return value
				}
			}
		}
	}
	return 0
}

func toInt64(value any) (int64, bool) {
	switch typed := value.(type) {
	case float64:
		return int64(typed), true
	case float32:
		return int64(typed), true
	case int64:
		return typed, true
	case int:
		return int64(typed), true
	case json.Number:
		parsed, err := typed.Int64()
		return parsed, err == nil
	case string:
		if strings.TrimSpace(typed) == "" {
			return 0, false
		}
		parsed, err := strconv.ParseInt(typed, 10, 64)
		return parsed, err == nil
	default:
		return 0, false
	}
}

func (s *Service) signozRawSample(ctx context.Context, scope NormalizedScope, signal string, fields []map[string]any, extraFilter string, limit int) ([]map[string]any, error) {
	filterExpr := s.scopeFilterExpression(scope)
	if extraFilter != "" {
		if filterExpr != "" {
			filterExpr = "(" + filterExpr + ") AND (" + extraFilter + ")"
		} else {
			filterExpr = extraFilter
		}
	}
	spec := map[string]any{
		"name":         "A",
		"signal":       signal,
		"selectFields": fields,
		"limit":        limit,
		"order": []map[string]any{
			{"key": map[string]any{"name": "timestamp"}, "direction": "desc"},
		},
	}
	if strings.TrimSpace(filterExpr) != "" {
		spec["filter"] = map[string]any{"expression": filterExpr}
	}
	payload := map[string]any{
		"schemaVersion": "v1",
		"start":         uint64(scope.Start.UTC().UnixMilli()),
		"end":           uint64(scope.End.UTC().UnixMilli()),
		"requestType":   "raw",
		"compositeQuery": map[string]any{
			"queries": []map[string]any{
				{"type": "builder_query", "spec": spec},
			},
		},
	}
	resp, err := s.signozQueryRange(ctx, payload)
	if err != nil {
		return nil, err
	}
	return extractRawRows(resp), nil
}

func extractRawRows(response map[string]any) []map[string]any {
	out := []map[string]any{}
	data, _ := response["data"].(map[string]any)
	results, _ := data["results"].([]any)
	for _, result := range results {
		item, ok := result.(map[string]any)
		if !ok {
			continue
		}
		rows, _ := item["rows"].([]any)
		for _, row := range rows {
			entry, ok := row.(map[string]any)
			if !ok {
				continue
			}
			out = append(out, entry)
		}
	}
	return out
}

func (s *Service) fetchEvidenceFromSynapse(ctx context.Context, scope NormalizedScope, preferredService string) signozEvidenceSummary {
	out := signozEvidenceSummary{
		ErrorLogSamples:  []string{},
		TraceIDs:         []string{},
		MetricHighlights: map[string]float64{},
	}

	serviceScope := scope
	if normalized := normalizeServiceName(preferredService); normalized != "" {
		serviceScope.Service = normalized
	}
	services, err := s.signozFetchServices(ctx, serviceScope)
	if err != nil {
		log.Printf("truth: signoz services fetch failed cluster=%s namespace=%s service=%s err=%v", firstNonEmpty(scope.Cluster, "all"), firstNonEmpty(scope.Namespace, "all"), firstNonEmpty(serviceScope.Service, "all"), err)
	} else {
		target := firstNonEmpty(serviceScope.Service, preferredService)
		for _, item := range services {
			if normalizeServiceName(item.ServiceName) != normalizeServiceName(target) && target != "" {
				continue
			}
			out.RequestCount = int64(item.NumCalls)
			out.ErrorRate = item.ErrorRate
			out.P95LatencyMs = item.Percentile99
			out.MetricHighlights["service.p99_ms"] = item.Percentile99
			out.MetricHighlights["service.error_rate"] = item.ErrorRate
			out.MetricHighlights["service.call_rate"] = item.CallRate
			break
		}
	}

	if logCount, err := s.signozCountScalar(ctx, serviceScope, "logs", ""); err == nil {
		out.LogCount = logCount
	} else {
		log.Printf("truth: signoz logs scalar failed cluster=%s namespace=%s service=%s err=%v", firstNonEmpty(scope.Cluster, "all"), firstNonEmpty(scope.Namespace, "all"), firstNonEmpty(serviceScope.Service, "all"), err)
	}
	if traceCount, err := s.signozCountScalar(ctx, serviceScope, "traces", ""); err == nil {
		out.TraceCount = int(traceCount)
	} else {
		log.Printf("truth: signoz traces scalar failed cluster=%s namespace=%s service=%s err=%v", firstNonEmpty(scope.Cluster, "all"), firstNonEmpty(scope.Namespace, "all"), firstNonEmpty(serviceScope.Service, "all"), err)
	}

	logRows, err := s.signozRawSample(ctx, serviceScope, "logs", []map[string]any{
		{"name": "body", "fieldContext": "log"},
		{"name": "trace_id", "fieldContext": "log"},
	}, "severity_text = 'ERROR'", 5)
	if err == nil {
		for _, row := range logRows {
			payload, _ := row["data"].(map[string]any)
			body := strings.TrimSpace(fmt.Sprintf("%v", payload["body"]))
			if body != "" && body != "<nil>" {
				out.ErrorLogSamples = append(out.ErrorLogSamples, body)
			}
			traceID := strings.TrimSpace(fmt.Sprintf("%v", payload["trace_id"]))
			if traceID != "" && traceID != "<nil>" {
				out.TraceIDs = append(out.TraceIDs, traceID)
			}
		}
	}

	traceRows, err := s.signozRawSample(ctx, serviceScope, "traces", []map[string]any{
		{"name": "trace_id", "fieldContext": "span"},
	}, "", 20)
	if err == nil {
		for _, row := range traceRows {
			payload, _ := row["data"].(map[string]any)
			traceID := strings.TrimSpace(fmt.Sprintf("%v", payload["trace_id"]))
			if traceID != "" && traceID != "<nil>" {
				out.TraceIDs = append(out.TraceIDs, traceID)
			}
		}
	}

	out.ErrorLogSamples = uniqueStrings(out.ErrorLogSamples)
	out.TraceIDs = uniqueStrings(out.TraceIDs)
	return out
}
