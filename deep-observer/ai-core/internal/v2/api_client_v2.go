package v2

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"sort"
	"strconv"
	"strings"
	"time"
)

type apiClient struct {
	baseURL string
	apiKey  string
	client  *http.Client
}

type serviceItem struct {
	ServiceName string  `json:"serviceName"`
	P99         float64 `json:"p99"`
	CallRate    float64 `json:"callRate"`
	NumCalls    uint64  `json:"numCalls"`
	ErrorRate   float64 `json:"errorRate"`
}

type dependencyItem struct {
	Parent    string  `json:"parent"`
	Child     string  `json:"child"`
	CallCount uint64  `json:"callCount"`
	ErrorRate float64 `json:"errorRate"`
	P95       float64 `json:"p95"`
	P99       float64 `json:"p99"`
}

func newAPIClient() *apiClient {
	base := strings.TrimRight(firstNonEmpty(
		strings.TrimSpace(os.Getenv("SIGNOZ_API_BASE_URL")),
		strings.TrimSpace(os.Getenv("SIGNOZ_BASE_URL")),
		"http://signoz:8080",
	), "/")
	key := firstNonEmpty(
		strings.TrimSpace(os.Getenv("SIGNOZ_API_KEY")),
		strings.TrimSpace(os.Getenv("signoz_api_key")),
	)
	return &apiClient{
		baseURL: base,
		apiKey:  key,
		client:  &http.Client{Timeout: 12 * time.Second},
	}
}

func (c *apiClient) request(ctx context.Context, method, path string, payload any, out any) error {
	var body io.Reader
	if payload != nil {
		enc, err := json.Marshal(payload)
		if err != nil {
			return err
		}
		body = bytes.NewReader(enc)
	}
	req, err := http.NewRequestWithContext(ctx, method, c.baseURL+path, body)
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	if c.apiKey != "" {
		req.Header.Set("Authorization", "Bearer "+c.apiKey)
		req.Header.Set("SIGNOZ-API-KEY", c.apiKey)
	}
	resp, err := c.client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(io.LimitReader(resp.Body, 8<<20))
	if err != nil {
		return err
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("synapse api %s failed status=%d body=%s", path, resp.StatusCode, strings.TrimSpace(string(raw)))
	}
	if out == nil || len(raw) == 0 {
		return nil
	}
	if err := json.Unmarshal(raw, out); err == nil {
		return nil
	}
	// wrapped response support
	var envelope map[string]any
	if err := json.Unmarshal(raw, &envelope); err != nil {
		return err
	}
	data, ok := envelope["data"]
	if !ok {
		return fmt.Errorf("unsupported response shape for %s", path)
	}
	encData, err := json.Marshal(data)
	if err != nil {
		return err
	}
	return json.Unmarshal(encData, out)
}

func (c *apiClient) tags(scope Scope, includeService bool) []map[string]any {
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

func (c *apiClient) fetchServices(ctx context.Context, scope Scope) ([]serviceItem, error) {
	payload := map[string]any{
		"start": strconv.FormatInt(scope.Start.UTC().UnixNano(), 10),
		"end":   strconv.FormatInt(scope.End.UTC().UnixNano(), 10),
		"tags":  c.tags(scope, false),
	}
	items := []serviceItem{}
	if err := c.request(ctx, http.MethodPost, "/api/v1/services", payload, &items); err != nil {
		return nil, err
	}
	out := make([]serviceItem, 0, len(items))
	for _, item := range items {
		item.ServiceName = normalizeService(item.ServiceName)
		if item.ServiceName == "" {
			continue
		}
		if scope.Service != "" && item.ServiceName != normalizeService(scope.Service) {
			continue
		}
		out = append(out, item)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ServiceName < out[j].ServiceName })
	return out, nil
}

func (c *apiClient) fetchDependencies(ctx context.Context, scope Scope) ([]dependencyItem, error) {
	payload := map[string]any{
		"start": strconv.FormatInt(scope.Start.UTC().UnixNano(), 10),
		"end":   strconv.FormatInt(scope.End.UTC().UnixNano(), 10),
		"tags":  c.tags(scope, false),
	}
	items := []dependencyItem{}
	if err := c.request(ctx, http.MethodPost, "/api/v1/dependency_graph", payload, &items); err != nil {
		return nil, err
	}
	return items, nil
}

func (c *apiClient) queryRange(ctx context.Context, payload map[string]any) (map[string]any, error) {
	resp := map[string]any{}
	if err := c.request(ctx, http.MethodPost, "/api/v5/query_range", payload, &resp); err != nil {
		return nil, err
	}
	return resp, nil
}

func (c *apiClient) scopeFilterExpr(scope Scope) string {
	filters := []string{}
	if scope.Service != "" {
		filters = append(filters, fmt.Sprintf("service.name = '%s'", strings.ReplaceAll(scope.Service, "'", "\\'")))
	}
	return strings.Join(filters, " AND ")
}

func (c *apiClient) countSignal(ctx context.Context, scope Scope, signal string) (int64, error) {
	spec := map[string]any{
		"name":   "A",
		"signal": signal,
		"aggregations": []map[string]any{
			{"expression": "count()", "alias": "count"},
		},
	}
	if expr := c.scopeFilterExpr(scope); expr != "" {
		spec["filter"] = map[string]any{"expression": expr}
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
	resp, err := c.queryRange(ctx, payload)
	if err != nil {
		return 0, err
	}
	return extractScalarCount(resp), nil
}

func (c *apiClient) fetchScopeFacets(ctx context.Context, scope Scope) ([]string, []string, []string, error) {
	clusters := map[string]struct{}{}
	namespaces := map[string]struct{}{}
	services := map[string]struct{}{}
	var firstErr error
	for _, signal := range []string{"traces", "logs"} {
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
		if expr := c.scopeFilterExpr(scope); expr != "" {
			spec["filter"] = map[string]any{"expression": expr}
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
		resp, err := c.queryRange(ctx, payload)
		if err != nil {
			if firstErr == nil {
				firstErr = err
			}
			continue
		}
		for _, row := range extractScalarRows(resp) {
			svc := normalizeService(fmt.Sprintf("%v", row["service.name"]))
			ns := strings.TrimSpace(fmt.Sprintf("%v", row["k8s.namespace.name"]))
			cl := strings.TrimSpace(fmt.Sprintf("%v", row["k8s.cluster.name"]))
			if svc != "" && svc != "<nil>" {
				services[svc] = struct{}{}
			}
			if ns != "" && ns != "<nil>" {
				namespaces[ns] = struct{}{}
			}
			if cl != "" && cl != "<nil>" {
				clusters[cl] = struct{}{}
			}
		}
	}
	return sortedKeys(clusters), sortedKeys(namespaces), sortedKeys(services), firstErr
}

func extractScalarRows(response map[string]any) []map[string]any {
	out := []map[string]any{}
	data, _ := response["data"].(map[string]any)
	results, _ := data["results"].([]any)
	for _, result := range results {
		item, ok := result.(map[string]any)
		if !ok {
			continue
		}
		columnsRaw, _ := item["columns"].([]any)
		colNames := []string{}
		for _, col := range columnsRaw {
			entry, _ := col.(map[string]any)
			colNames = append(colNames, strings.TrimSpace(fmt.Sprintf("%v", entry["name"])))
		}
		rows, _ := item["data"].([]any)
		for _, row := range rows {
			values, ok := row.([]any)
			if !ok {
				continue
			}
			entry := map[string]any{}
			for idx := range values {
				if idx < len(colNames) && colNames[idx] != "" {
					entry[colNames[idx]] = values[idx]
				}
			}
			out = append(out, entry)
		}
	}
	return out
}

func extractScalarCount(response map[string]any) int64 {
	data, _ := response["data"].(map[string]any)
	results, _ := data["results"].([]any)
	for _, result := range results {
		item, _ := result.(map[string]any)
		rows, _ := item["data"].([]any)
		for _, row := range rows {
			values, ok := row.([]any)
			if !ok || len(values) == 0 {
				continue
			}
			for i := len(values) - 1; i >= 0; i-- {
				switch typed := values[i].(type) {
				case float64:
					return int64(typed)
				case int64:
					return typed
				case string:
					if parsed, err := strconv.ParseInt(typed, 10, 64); err == nil {
						return parsed
					}
				}
			}
		}
	}
	return 0
}

func sortedKeys(set map[string]struct{}) []string {
	out := make([]string, 0, len(set))
	for value := range set {
		if value != "" {
			out = append(out, value)
		}
	}
	sort.Strings(out)
	return out
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if strings.TrimSpace(value) != "" {
			return strings.TrimSpace(value)
		}
	}
	return ""
}

