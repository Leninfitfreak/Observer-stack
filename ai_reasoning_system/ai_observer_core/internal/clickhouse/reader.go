package clickhouse

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"

	"ai_observer_core/internal/config"
)

type ServiceTelemetry struct {
	Timestamp    time.Time `json:"timestamp"`
	Cluster      string    `json:"cluster"`
	Namespace    string    `json:"namespace"`
	Service      string    `json:"service"`
	SpanCount    float64   `json:"span_count"`
	AvgLatencyMs float64   `json:"avg_latency_ms"`
	ErrorCount   float64   `json:"error_count"`
	LogCount     float64   `json:"log_count"`
	MetricCount  float64   `json:"metric_count"`
}

type Reader struct {
	cfg    config.Config
	http   *http.Client
	base   string
}

func New(cfg config.Config) (*Reader, error) {
	return &Reader{cfg: cfg, http: &http.Client{Timeout: 30 * time.Second}, base: fmt.Sprintf("http://%s:%d", cfg.ClickHouseHost, cfg.ClickHousePort)}, nil
}

func (r *Reader) Health(ctx context.Context) error {
	_, err := r.query(ctx, "SELECT 1 FORMAT TabSeparated")
	return err
}

func (r *Reader) FetchTelemetryWindow(ctx context.Context, lookbackMinutes int) ([]ServiceTelemetry, error) {
	query := fmt.Sprintf(`
WITH trace_data AS (
	SELECT
		toStartOfMinute(timestamp) AS ts,
		ifNull(nullIf(resources_string['k8s.cluster.name'], ''), '%s') AS cluster,
		ifNull(nullIf(resources_string['k8s.namespace.name'], ''), ifNull(nullIf(resources_string['deployment.environment'], ''), 'unknown')) AS namespace,
		serviceName AS service,
		count() AS span_count,
		avg(duration_nano)/1000000 AS avg_latency_ms,
		countIf(has_error = true) AS error_count
	FROM signoz_traces.distributed_signoz_index_v3
	WHERE timestamp > now() - toIntervalMinute(%d) AND serviceName != ''
	GROUP BY ts, cluster, namespace, service
), log_data AS (
	SELECT
		toStartOfMinute(fromUnixTimestamp64Nano(timestamp)) AS ts,
		ifNull(nullIf(resources_string['k8s.cluster.name'], ''), '%s') AS cluster,
		ifNull(nullIf(resources_string['k8s.namespace.name'], ''), ifNull(nullIf(resources_string['deployment.environment'], ''), 'unknown')) AS namespace,
		ifNull(nullIf(resources_string['service.name'], ''), 'unknown') AS service,
		count() AS log_count
	FROM signoz_logs.distributed_logs_v2
	WHERE fromUnixTimestamp64Nano(timestamp) > now() - toIntervalMinute(%d)
	GROUP BY ts, cluster, namespace, service
), metric_data AS (
	SELECT
		toStartOfMinute(toDateTime(unix_milli / 1000)) AS ts,
		ifNull(nullIf(resource_attrs['k8s.cluster.name'], ''), '%s') AS cluster,
		ifNull(nullIf(resource_attrs['k8s.namespace.name'], ''), 'unknown') AS namespace,
		ifNull(nullIf(resource_attrs['service.name'], ''), 'unknown') AS service,
		count() AS metric_count
	FROM signoz_metrics.distributed_time_series_v4
	WHERE unix_milli >= (toUnixTimestamp(now() - toIntervalMinute(%d)) * 1000)
	GROUP BY ts, cluster, namespace, service
), base_keys AS (
	SELECT ts, cluster, namespace, service FROM trace_data
	UNION ALL
	SELECT ts, cluster, namespace, service FROM log_data
	UNION ALL
	SELECT ts, cluster, namespace, service FROM metric_data
), deduped_keys AS (
	SELECT ts, cluster, namespace, service
	FROM base_keys
	GROUP BY ts, cluster, namespace, service
)
SELECT
	k.ts,
	k.cluster,
	k.namespace,
	k.service,
	ifNull(t.span_count, 0),
	ifNull(t.avg_latency_ms, 0),
	ifNull(t.error_count, 0),
	ifNull(l.log_count, 0),
	ifNull(m.metric_count, 0)
FROM deduped_keys k
LEFT JOIN trace_data t ON k.ts=t.ts AND k.cluster=t.cluster AND k.namespace=t.namespace AND k.service=t.service
LEFT JOIN log_data l ON k.ts=l.ts AND k.cluster=l.cluster AND k.namespace=l.namespace AND k.service=l.service
LEFT JOIN metric_data m ON k.ts=m.ts AND k.cluster=m.cluster AND k.namespace=m.namespace AND k.service=m.service
WHERE ('%s'='' OR k.namespace='%s') AND ('%s'='' OR k.service='%s')
ORDER BY k.ts DESC
FORMAT TabSeparated`, r.cfg.ClusterID, lookbackMinutes, r.cfg.ClusterID, lookbackMinutes, r.cfg.ClusterID, lookbackMinutes, r.cfg.NamespaceFilter, r.cfg.NamespaceFilter, r.cfg.ServiceFilter, r.cfg.ServiceFilter)
	body, err := r.query(ctx, query)
	if err != nil { return nil, err }
	rows := strings.Split(strings.TrimSpace(string(body)), "\n")
	result := make([]ServiceTelemetry, 0, len(rows))
	for _, line := range rows {
		if strings.TrimSpace(line) == "" { continue }
		parts := strings.Split(line, "\t")
		if len(parts) < 9 { continue }
		ts, err := time.Parse("2006-01-02 15:04:05", parts[0])
		if err != nil { continue }
		spanCount, _ := strconv.ParseFloat(parts[4], 64)
		latency, _ := strconv.ParseFloat(parts[5], 64)
		errorCount, _ := strconv.ParseFloat(parts[6], 64)
		logCount, _ := strconv.ParseFloat(parts[7], 64)
		metricCount, _ := strconv.ParseFloat(parts[8], 64)
		result = append(result, ServiceTelemetry{Timestamp: ts, Cluster: parts[1], Namespace: parts[2], Service: parts[3], SpanCount: spanCount, AvgLatencyMs: latency, ErrorCount: errorCount, LogCount: logCount, MetricCount: metricCount})
	}
	return result, nil
}

func (r *Reader) query(ctx context.Context, sql string) ([]byte, error) {
	endpoint := r.base + "/?query=" + url.QueryEscape(sql)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, bytes.NewBuffer(nil))
	if err != nil { return nil, err }
	if r.cfg.ClickHouseUser != "" { req.SetBasicAuth(r.cfg.ClickHouseUser, r.cfg.ClickHousePassword) }
	resp, err := r.http.Do(req)
	if err != nil { return nil, err }
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode >= 300 {
		return nil, fmt.Errorf("clickhouse_http_%d: %s", resp.StatusCode, strings.TrimSpace(string(body)))
	}
	return body, nil
}
