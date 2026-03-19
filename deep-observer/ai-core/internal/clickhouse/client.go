package clickhouse

import (
	"context"
	"fmt"
	"math"
	"sort"
	"strings"
	"time"

	ch "github.com/ClickHouse/clickhouse-go/v2"
	"github.com/ClickHouse/clickhouse-go/v2/lib/driver"

	"deep-observer/ai-core/internal/config"
)

const (
	metricsTable = "signoz_metrics.distributed_time_series_v4"
	samplesTable = "signoz_metrics.distributed_samples_v4"
	logsTable    = "signoz_logs.distributed_logs_v2"
	tracesTable  = "signoz_traces.distributed_signoz_index_v3"
)

type Client struct {
	conn driver.Conn
}

type Filters struct {
	Cluster   string
	Namespace string
	Service   string
	Start     time.Time
	End       time.Time
}

type ServiceCandidate struct {
	Cluster   string
	Namespace string
	Service   string
}

type ServiceSelection struct {
	Cluster   string
	Namespace string
	Service   string
}

type Snapshot struct {
	Filters              Filters            `json:"filters"`
	ObservedAt           time.Time          `json:"observed_at"`
	RequestCount         int64              `json:"request_count"`
	ErrorCount           int64              `json:"error_count"`
	ErrorRate            float64            `json:"error_rate"`
	AvgLatencyMs         float64            `json:"avg_latency_ms"`
	P95LatencyMs         float64            `json:"p95_latency_ms"`
	BaselineErrorRate    float64            `json:"baseline_error_rate"`
	BaselineLatencyMs    float64            `json:"baseline_latency_ms"`
	BaselineLatencyStdMs float64            `json:"baseline_latency_std_ms"`
	LatencyZScore        float64            `json:"latency_zscore"`
	CPUUtilization       float64            `json:"cpu_utilization"`
	MemoryUtilization    float64            `json:"memory_utilization"`
	LogCount             int64              `json:"log_count"`
	ErrorLogs            []string           `json:"error_logs"`
	TraceIDs             []string           `json:"trace_ids"`
	MetricHighlights     map[string]float64 `json:"metric_highlights"`
	TelemetryQuality     map[string]string  `json:"telemetry_quality"`
}

func NewClient(ctx context.Context, cfg config.ClickHouseConfig) (*Client, error) {
	conn, err := ch.Open(&ch.Options{
		Addr: []string{fmt.Sprintf("%s:%d", cfg.Host, cfg.Port)},
		Auth: ch.Auth{
			Database: cfg.Database,
			Username: cfg.User,
			Password: cfg.Password,
		},
		Settings: ch.Settings{
			"max_execution_time": 30,
		},
		DialTimeout:     10 * time.Second,
		MaxOpenConns:    5,
		MaxIdleConns:    5,
		ConnMaxLifetime: time.Hour,
		Compression:     &ch.Compression{Method: ch.CompressionLZ4},
		ClientInfo:      ch.ClientInfo{Products: []struct{ Name, Version string }{{Name: "deep-observer-ai-core", Version: "1.0.0"}}},
		Protocol:        ch.Native,
	})
	if err != nil {
		return nil, err
	}
	if err := conn.Ping(ctx); err != nil {
		return nil, err
	}
	return &Client{conn: conn}, nil
}

func (c *Client) Close() error {
	return c.conn.Close()
}

func (c *Client) ListActiveServices(ctx context.Context, lookback time.Duration, selection ServiceSelection) ([]ServiceCandidate, error) {
	candidates := map[string]ServiceCandidate{}
	serviceFilter := canonicalizeServiceName(selection.Service)
	namespaceFilter := strings.ToLower(strings.TrimSpace(selection.Namespace))
	clusterFilter := strings.ToLower(strings.TrimSpace(selection.Cluster))
	where := []string{
		fmt.Sprintf("timestamp >= now() - INTERVAL %d MINUTE", int(lookback.Minutes())),
		"coalesce(nullIf(serviceName, ''), nullIf(resources_string['service.name'], ''), nullIf(resources_string['k8s.service.name'], ''), nullIf(resources_string['k8s.deployment.name'], '')) != ''",
	}
	if clusterFilter != "" {
		where = append(where, fmt.Sprintf("resources_string['k8s.cluster.name'] = '%s'", escape(clusterFilter)))
	}
	if namespaceFilter != "" {
		where = append(where, fmt.Sprintf("resources_string['k8s.namespace.name'] = '%s'", escape(namespaceFilter)))
	}

	traceRows, err := c.conn.Query(ctx, fmt.Sprintf(`
		SELECT
			coalesce(
				nullIf(serviceName, ''),
				nullIf(resources_string['service.name'], ''),
				nullIf(resources_string['k8s.service.name'], ''),
				nullIf(resources_string['k8s.deployment.name'], '')
			) AS service,
			ifNull(nullIf(resources_string['k8s.namespace.name'], ''), '') AS namespace,
			ifNull(nullIf(resources_string['k8s.cluster.name'], ''), '') AS cluster
		FROM %s
		WHERE %s
		GROUP BY service, namespace, cluster
		LIMIT 100
	`, tracesTable, strings.Join(where, " AND ")))
	if err == nil {
		defer traceRows.Close()
		for traceRows.Next() {
			var candidate ServiceCandidate
			if scanErr := traceRows.Scan(&candidate.Service, &candidate.Namespace, &candidate.Cluster); scanErr == nil {
				candidate.Service = canonicalizeServiceName(candidate.Service)
				candidate.Namespace = canonicalNamespace(candidate.Namespace)
				candidate.Cluster = canonicalCluster(candidate.Cluster)
				if serviceFilter != "" && candidate.Service != serviceFilter {
					continue
				}
				if ignoredService(candidate.Service) {
					continue
				}
				candidates[candidate.Cluster+"|"+candidate.Namespace+"|"+candidate.Service] = candidate
			}
		}
	}

	metricRows, err := c.conn.Query(ctx, fmt.Sprintf(`
		SELECT
			coalesce(
				nullIf(resource_attrs['service.name'], ''),
				nullIf(resource_attrs['k8s.service.name'], ''),
				nullIf(resource_attrs['k8s.deployment.name'], '')
			) AS service,
			ifNull(nullIf(resource_attrs['k8s.namespace.name'], ''), '') AS namespace,
			ifNull(nullIf(resource_attrs['k8s.cluster.name'], ''), '') AS cluster
		FROM %s
		WHERE unix_milli >= %d
		  AND unix_milli < %d
		  AND coalesce(nullIf(resource_attrs['service.name'], ''), nullIf(resource_attrs['k8s.service.name'], ''), nullIf(resource_attrs['k8s.deployment.name'], '')) != ''
		GROUP BY service, namespace, cluster
		LIMIT 100
	`, metricsTable, time.Now().UTC().Add(-lookback).UnixMilli(), time.Now().UTC().UnixMilli()))
	if err == nil {
		defer metricRows.Close()
		for metricRows.Next() {
			var candidate ServiceCandidate
			if scanErr := metricRows.Scan(&candidate.Service, &candidate.Namespace, &candidate.Cluster); scanErr == nil {
				candidate.Service = canonicalizeServiceName(candidate.Service)
				candidate.Namespace = canonicalNamespace(candidate.Namespace)
				candidate.Cluster = canonicalCluster(candidate.Cluster)
				if clusterFilter != "" && clusterFilter != candidate.Cluster {
					continue
				}
				if namespaceFilter != "" && namespaceFilter != candidate.Namespace {
					continue
				}
				if serviceFilter != "" && serviceFilter != candidate.Service {
					continue
				}
				if ignoredService(candidate.Service) {
					continue
				}
				candidates[candidate.Cluster+"|"+candidate.Namespace+"|"+candidate.Service] = candidate
			}
		}
	}

	services := make([]ServiceCandidate, 0, len(candidates))
	for _, candidate := range candidates {
		services = append(services, candidate)
	}
	sort.Slice(services, func(i, j int) bool {
		if services[i].Service == services[j].Service {
			if services[i].Namespace == services[j].Namespace {
				return services[i].Cluster < services[j].Cluster
			}
			return services[i].Namespace < services[j].Namespace
		}
		return services[i].Service < services[j].Service
	})
	return services, nil
}

func (c *Client) ReadSnapshot(ctx context.Context, filters Filters, baselineWindow time.Duration) (Snapshot, error) {
	snapshot := Snapshot{
		Filters:          filters,
		ObservedAt:       filters.End,
		ErrorLogs:        []string{},
		TraceIDs:         []string{},
		MetricHighlights: map[string]float64{},
		TelemetryQuality: map[string]string{},
	}

	where := traceWhere(filters)
	var requestCount, errorCount int64
	var avgLatency, p95Latency, baselineErrorRate, baselineLatency, baselineLatencyStd float64

	mainQuery := fmt.Sprintf(`
		SELECT
			toInt64(count()) AS request_count,
			toInt64(sum(toUInt64(hasError))) AS error_count,
			if(request_count = 0, 0, error_count / request_count) AS error_rate,
			avg(durationNano) / 1000000 AS avg_latency_ms,
			quantile(0.95)(durationNano) / 1000000 AS p95_latency_ms,
			max(timestamp) AS latest_trace_at
		FROM %s
		WHERE %s
	`, tracesTable, where)
	var latestTraceAt time.Time
	if err := c.conn.QueryRow(ctx, mainQuery).Scan(&requestCount, &errorCount, &snapshot.ErrorRate, &avgLatency, &p95Latency, &latestTraceAt); err != nil {
		return snapshot, err
	}
	snapshot.RequestCount = requestCount
	snapshot.ErrorCount = errorCount
	snapshot.AvgLatencyMs = avgLatency
	snapshot.P95LatencyMs = p95Latency
	if !latestTraceAt.IsZero() {
		snapshot.ObservedAt = latestTraceAt.UTC()
	}
	sanitizeSnapshot(&snapshot)

	baselineFilters := filters
	baselineFilters.Start = filters.Start.Add(-baselineWindow)
	baselineFilters.End = filters.Start
	baselineQuery := fmt.Sprintf(`
		SELECT
			if(count() = 0, 0,
				sum(toUInt64(hasError)) / count()
			) AS baseline_error_rate,
			avg(durationNano) / 1000000 AS baseline_latency_ms,
			stddevPop(durationNano) / 1000000 AS baseline_latency_std_ms
		FROM %s
		WHERE %s
	`, tracesTable, traceWhere(baselineFilters))
	if err := c.conn.QueryRow(ctx, baselineQuery).Scan(&baselineErrorRate, &baselineLatency, &baselineLatencyStd); err != nil {
		return snapshot, err
	}
	snapshot.BaselineErrorRate = baselineErrorRate
	snapshot.BaselineLatencyMs = baselineLatency
	snapshot.BaselineLatencyStdMs = baselineLatencyStd
	if snapshot.BaselineLatencyStdMs > 0 {
		snapshot.LatencyZScore = (snapshot.P95LatencyMs - snapshot.BaselineLatencyMs) / snapshot.BaselineLatencyStdMs
	}
	sanitizeSnapshot(&snapshot)

	logQuery := fmt.Sprintf(`
		SELECT
			toInt64(count()) AS log_count,
			max(timestamp) AS latest_log_at,
			groupArrayIf(5)(substring(toString(body), 1, 240),
				lowerUTF8(severity_text) IN ('error', 'fatal', 'warn', 'warning') OR
				severity_number >= 13 OR
				positionCaseInsensitive(body, 'error') > 0 OR
				positionCaseInsensitive(body, 'exception') > 0 OR
				positionCaseInsensitive(body, 'backoff') > 0 OR
				positionCaseInsensitive(body, 'failed') > 0
			) AS error_logs
		FROM %s
		WHERE %s
	`, logsTable, logWhere(filters))
	errorLogs := []string{}
	var latestLogAt int64
	if err := c.conn.QueryRow(ctx, logQuery).Scan(&snapshot.LogCount, &latestLogAt, &errorLogs); err == nil {
		snapshot.ErrorLogs = errorLogs
		if latestLogAt > 0 {
			latestLogTime := time.Unix(0, latestLogAt).UTC()
			if latestLogTime.After(snapshot.ObservedAt) {
				snapshot.ObservedAt = latestLogTime
			}
		}
	}

	traceIDQuery := fmt.Sprintf(`
		SELECT groupArray(5)(traceID)
		FROM %s
		WHERE %s
	`, tracesTable, where)
	traceIDs := []string{}
	if err := c.conn.QueryRow(ctx, traceIDQuery).Scan(&traceIDs); err == nil {
		snapshot.TraceIDs = traceIDs
	}

	metricQuery := fmt.Sprintf(`
		SELECT
			ts.metric_name,
			argMax(samples.value, samples.unix_milli) AS latest_value,
			max(samples.unix_milli) AS latest_unix_milli
		FROM %s AS samples
		INNER JOIN %s AS ts USING fingerprint
		WHERE samples.unix_milli >= %d AND samples.unix_milli < %d
		  AND (%s)
		  AND (%s)
		  AND (%s)
		  AND (
			positionCaseInsensitive(ts.metric_name, 'cpu') > 0 OR
			positionCaseInsensitive(ts.metric_name, 'memory') > 0 OR
			positionCaseInsensitive(ts.metric_name, 'latency') > 0 OR
			positionCaseInsensitive(ts.metric_name, 'error') > 0 OR
			positionCaseInsensitive(ts.metric_name, 'duration') > 0 OR
			positionCaseInsensitive(ts.metric_name, 'request') > 0 OR
			positionCaseInsensitive(ts.metric_name, 'messag') > 0 OR
			positionCaseInsensitive(ts.metric_name, 'broker') > 0 OR
			positionCaseInsensitive(ts.metric_name, 'topic') > 0 OR
			positionCaseInsensitive(ts.metric_name, 'lag') > 0 OR
			positionCaseInsensitive(ts.metric_name, 'queue') > 0 OR
			positionCaseInsensitive(ts.metric_name, 'db') > 0 OR
			positionCaseInsensitive(ts.metric_name, 'database') > 0 OR
			positionCaseInsensitive(ts.metric_name, 'jvm') > 0 OR
			positionCaseInsensitive(ts.metric_name, 'process') > 0
		  )
		  GROUP BY ts.metric_name
		  LIMIT 40
	`, samplesTable, metricsTable, filters.Start.UnixMilli(), filters.End.UnixMilli(),
		matchMapExprOptional("ts.resource_attrs", "k8s.cluster.name", filters.Cluster),
		matchMapExprOptional("ts.resource_attrs", "k8s.namespace.name", filters.Namespace),
		matchMetricServiceExprWithAlias("ts", filters.Service),
	)
	rows, err := c.conn.Query(ctx, metricQuery)
	var latestMetricAt int64
	if err == nil {
		defer rows.Close()
		for rows.Next() {
			var name string
			var value float64
			var observedAt int64
			if scanErr := rows.Scan(&name, &value, &observedAt); scanErr == nil {
				snapshot.MetricHighlights[name] = value
				if observedAt > latestMetricAt {
					latestMetricAt = observedAt
				}
			}
		}
	}
	applyRuntimeMetricSignals(&snapshot)
	metricsCountQuery := fmt.Sprintf(`
		SELECT toInt64(count())
		FROM %s AS samples
		INNER JOIN %s AS ts USING fingerprint
		WHERE samples.unix_milli >= %d AND samples.unix_milli < %d
		  AND (%s)
		  AND (%s)
		  AND (%s)
	`, samplesTable, metricsTable, filters.Start.UnixMilli(), filters.End.UnixMilli(),
		matchMapExprOptional("ts.resource_attrs", "k8s.cluster.name", filters.Cluster),
		matchMapExprOptional("ts.resource_attrs", "k8s.namespace.name", filters.Namespace),
		matchMetricServiceExprWithAlias("ts", filters.Service),
	)
	var metricsDatapoints int64
	if err := c.conn.QueryRow(ctx, metricsCountQuery).Scan(&metricsDatapoints); err == nil && metricsDatapoints > 0 {
		snapshot.MetricHighlights["metrics.datapoints"] = float64(metricsDatapoints)
	}
	snapshot.TelemetryQuality = classifyTelemetryQuality(snapshot, latestTraceAt, latestLogAt, latestMetricAt)

	return snapshot, nil
}

func sanitizeSnapshot(snapshot *Snapshot) {
	if math.IsNaN(snapshot.ErrorRate) || math.IsInf(snapshot.ErrorRate, 0) {
		snapshot.ErrorRate = 0
	}
	if math.IsNaN(snapshot.AvgLatencyMs) || math.IsInf(snapshot.AvgLatencyMs, 0) {
		snapshot.AvgLatencyMs = 0
	}
	if math.IsNaN(snapshot.P95LatencyMs) || math.IsInf(snapshot.P95LatencyMs, 0) {
		snapshot.P95LatencyMs = 0
	}
	if math.IsNaN(snapshot.BaselineErrorRate) || math.IsInf(snapshot.BaselineErrorRate, 0) {
		snapshot.BaselineErrorRate = 0
	}
	if math.IsNaN(snapshot.BaselineLatencyMs) || math.IsInf(snapshot.BaselineLatencyMs, 0) {
		snapshot.BaselineLatencyMs = 0
	}
	if math.IsNaN(snapshot.BaselineLatencyStdMs) || math.IsInf(snapshot.BaselineLatencyStdMs, 0) {
		snapshot.BaselineLatencyStdMs = 0
	}
	if math.IsNaN(snapshot.LatencyZScore) || math.IsInf(snapshot.LatencyZScore, 0) {
		snapshot.LatencyZScore = 0
	}
	if math.IsNaN(snapshot.CPUUtilization) || math.IsInf(snapshot.CPUUtilization, 0) {
		snapshot.CPUUtilization = 0
	}
	if math.IsNaN(snapshot.MemoryUtilization) || math.IsInf(snapshot.MemoryUtilization, 0) {
		snapshot.MemoryUtilization = 0
	}
}

func traceWhere(filters Filters) string {
	parts := []string{
		fmt.Sprintf("timestamp >= toDateTime64(%d / 1000.0, 3)", filters.Start.UnixMilli()),
		fmt.Sprintf("timestamp < toDateTime64(%d / 1000.0, 3)", filters.End.UnixMilli()),
		"positionCaseInsensitive(name, '/actuator/prometheus') = 0",
		"positionCaseInsensitive(name, '/actuator/health') = 0",
		"positionCaseInsensitive(attributes_string['http.route'], '/actuator/prometheus') = 0",
		"positionCaseInsensitive(attributes_string['http.route'], '/actuator/health') = 0",
	}
	if filters.Service != "" {
		parts = append(parts, fmt.Sprintf("replaceRegexpOne(replaceRegexpOne(lowerUTF8(coalesce(nullIf(serviceName, ''), nullIf(resources_string['service.name'], ''), nullIf(resources_string['k8s.service.name'], ''), nullIf(resources_string['k8s.deployment.name'], ''))), '-[a-f0-9]{8,10}-[a-z0-9]{5}$', ''), '-[a-f0-9]{8,10}$', '') = '%s'", escape(canonicalizeServiceName(filters.Service))))
	}
	if filters.Namespace != "" {
		parts = append(parts, fmt.Sprintf("resources_string['k8s.namespace.name'] = '%s'", escape(filters.Namespace)))
	}
	if filters.Cluster != "" {
		parts = append(parts, fmt.Sprintf("resources_string['k8s.cluster.name'] = '%s'", escape(filters.Cluster)))
	}
	return strings.Join(parts, " AND ")
}

func logWhere(filters Filters) string {
	parts := []string{
		fmt.Sprintf("timestamp >= %d", filters.Start.UnixNano()),
		fmt.Sprintf("timestamp < %d", filters.End.UnixNano()),
	}
	if filters.Service != "" {
		parts = append(parts, fmt.Sprintf("replaceRegexpOne(replaceRegexpOne(lowerUTF8(coalesce(nullIf(resources_string['service.name'], ''), nullIf(resources_string['k8s.service.name'], ''), nullIf(resources_string['k8s.deployment.name'], ''))), '-[a-f0-9]{8,10}-[a-z0-9]{5}$', ''), '-[a-f0-9]{8,10}$', '') = '%s'", escape(canonicalizeServiceName(filters.Service))))
	}
	if filters.Namespace != "" {
		parts = append(parts, fmt.Sprintf("resources_string['k8s.namespace.name'] = '%s'", escape(filters.Namespace)))
	}
	if filters.Cluster != "" {
		parts = append(parts, fmt.Sprintf("resources_string['k8s.cluster.name'] = '%s'", escape(filters.Cluster)))
	}
	return strings.Join(parts, " AND ")
}

func matchMapExpr(column, key, value string) string {
	if value == "" {
		return "1 = 1"
	}
	return fmt.Sprintf("positionCaseInsensitive(%s['%s'], '%s') > 0", column, escape(key), escape(value))
}

func matchMapExprOptional(column, key, value string) string {
	if value == "" {
		return "1 = 1"
	}
	return fmt.Sprintf("%s['%s'] = '%s'", column, escape(key), escape(value))
}

func matchMetricServiceExpr(service string) string {
	return matchMetricServiceExprWithAlias("", service)
}

func matchMetricServiceExprWithAlias(alias, service string) string {
	if strings.TrimSpace(service) == "" {
		return "1 = 1"
	}
	canonical := escape(canonicalizeServiceName(service))
	column := "resource_attrs"
	if strings.TrimSpace(alias) != "" {
		column = alias + ".resource_attrs"
	}
	return fmt.Sprintf(
		"replaceRegexpOne(replaceRegexpOne(lowerUTF8(coalesce(nullIf(%s['service.name'], ''), nullIf(%s['k8s.service.name'], ''), nullIf(%s['k8s.deployment.name'], ''))), '-[a-f0-9]{8,10}-[a-z0-9]{5}$', ''), '-[a-f0-9]{8,10}$', '') = '%s'",
		column, column, column,
		canonical,
	)
}

func escape(value string) string {
	return strings.ReplaceAll(value, "'", "''")
}

func ignoredService(service string) bool {
	value := strings.ToLower(strings.TrimSpace(service))
	if value == "" {
		return true
	}
	return InferTopologyNodeType(CanonicalTopologyNodeID(value)) != "service"
}

func IsIgnoredService(service string) bool {
	return ignoredService(service)
}

func applyRuntimeMetricSignals(snapshot *Snapshot) {
	memoryUsed := 0.0
	memoryLimit := 0.0
	for name, value := range snapshot.MetricHighlights {
		lower := strings.ToLower(name)
		switch {
		case strings.Contains(lower, "cpu") && strings.Contains(lower, "utilization"):
			snapshot.CPUUtilization = maxFloat(snapshot.CPUUtilization, value)
		case strings.Contains(lower, "memory") && strings.Contains(lower, "utilization"):
			snapshot.MemoryUtilization = maxFloat(snapshot.MemoryUtilization, value)
		case lower == "jvm.memory.used":
			memoryUsed = maxFloat(memoryUsed, value)
		case lower == "jvm.memory.limit":
			memoryLimit = maxFloat(memoryLimit, value)
		}
	}
	if snapshot.MemoryUtilization == 0 && memoryUsed > 0 && memoryLimit > 0 {
		snapshot.MemoryUtilization = (memoryUsed / memoryLimit) * 100
	}
}

func classifyTelemetryQuality(snapshot Snapshot, latestTraceAt time.Time, latestLogAt int64, latestMetricAt int64) map[string]string {
	quality := map[string]string{
		"traces":  "missing",
		"logs":    "missing",
		"metrics": "missing",
	}
	if snapshot.RequestCount > 0 || len(snapshot.TraceIDs) > 0 {
		quality["traces"] = "present"
		if snapshot.RequestCount > 0 && snapshot.RequestCount < 20 {
			quality["traces"] = "sparse"
		}
		if !latestTraceAt.IsZero() && snapshot.End().Sub(latestTraceAt.UTC()) > 15*time.Minute {
			quality["traces"] = "stale"
		}
	}
	if snapshot.LogCount > 0 {
		quality["logs"] = "present"
		if snapshot.LogCount < 3 {
			quality["logs"] = "sparse"
		}
		if latestLogAt > 0 {
			logTime := time.Unix(0, latestLogAt).UTC()
			if snapshot.End().Sub(logTime) > 15*time.Minute {
				quality["logs"] = "stale"
			}
		}
	}
	meaningfulMetrics := 0
	allZero := true
	for name, value := range snapshot.MetricHighlights {
		if name == "metrics.datapoints" {
			continue
		}
		meaningfulMetrics++
		if math.Abs(value) > 0 {
			allZero = false
		}
	}
	switch {
	case meaningfulMetrics == 0:
		quality["metrics"] = "missing"
	case allZero:
		quality["metrics"] = "zero"
	case meaningfulMetrics < 3:
		quality["metrics"] = "sparse"
	default:
		quality["metrics"] = "present"
	}
	if latestMetricAt > 0 {
		metricTime := time.UnixMilli(latestMetricAt).UTC()
		if snapshot.End().Sub(metricTime) > 15*time.Minute {
			quality["metrics"] = "stale"
		}
	}
	if snapshot.RequestCount == 0 && quality["traces"] == "present" {
		quality["traces"] = "contradictory"
	}
	return quality
}

func (s Snapshot) End() time.Time {
	if !s.Filters.End.IsZero() {
		return s.Filters.End
	}
	return s.ObservedAt
}

func maxFloat(left, right float64) float64 {
	if right > left {
		return right
	}
	return left
}
