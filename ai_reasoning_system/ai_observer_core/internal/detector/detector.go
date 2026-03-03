package detector

import (
	"math"
	"sort"

	"ai_observer_core/internal/clickhouse"
)

type Snapshot struct {
	Current  clickhouse.ServiceTelemetry `json:"current"`
	Baseline map[string]float64          `json:"baseline"`
	ZScores  map[string]float64          `json:"z_scores"`
	Signals  []string                    `json:"signals"`
	Score    float64                     `json:"score"`
}

type Anomaly struct {
	Cluster   string   `json:"cluster"`
	Namespace string   `json:"namespace"`
	Service   string   `json:"service"`
	Snapshot  Snapshot `json:"snapshot"`
}

type Detector struct { Threshold float64 }

func (d Detector) Detect(rows []clickhouse.ServiceTelemetry) []Anomaly {
	groups := map[string][]clickhouse.ServiceTelemetry{}
	for _, row := range rows { groups[row.Cluster+"|"+row.Namespace+"|"+row.Service] = append(groups[row.Cluster+"|"+row.Namespace+"|"+row.Service], row) }
	anomalies := make([]Anomaly, 0)
	for _, svcRows := range groups {
		if len(svcRows) < 5 { continue }
		sort.Slice(svcRows, func(i, j int) bool { return svcRows[i].Timestamp.Before(svcRows[j].Timestamp) })
		current := svcRows[len(svcRows)-1]
		baselineRows := svcRows[:len(svcRows)-1]
		spanSeries := series(baselineRows, func(r clickhouse.ServiceTelemetry) float64 { return r.SpanCount })
		latSeries := series(baselineRows, func(r clickhouse.ServiceTelemetry) float64 { return r.AvgLatencyMs })
		errSeries := series(baselineRows, func(r clickhouse.ServiceTelemetry) float64 { return r.ErrorCount })
		logSeries := series(baselineRows, func(r clickhouse.ServiceTelemetry) float64 { return r.LogCount })
		metricSeries := series(baselineRows, func(r clickhouse.ServiceTelemetry) float64 { return r.MetricCount })
		z := map[string]float64{
			"span_count":     zscore(current.SpanCount, spanSeries),
			"avg_latency_ms": zscore(current.AvgLatencyMs, latSeries),
			"error_count":    zscore(current.ErrorCount, errSeries),
			"log_count":      zscore(current.LogCount, logSeries),
			"metric_count":   zscore(current.MetricCount, metricSeries),
		}
		signals := make([]string, 0)
		maxScore := 0.0
		for metric, score := range z {
			abs := math.Abs(score)
			if abs > maxScore { maxScore = abs }
			if abs >= d.Threshold { signals = append(signals, metric) }
		}
		if len(signals) == 0 { continue }
		anomalies = append(anomalies, Anomaly{Cluster: current.Cluster, Namespace: current.Namespace, Service: current.Service, Snapshot: Snapshot{Current: current, Baseline: map[string]float64{"span_count": mean(spanSeries), "avg_latency_ms": mean(latSeries), "error_count": mean(errSeries), "log_count": mean(logSeries), "metric_count": mean(metricSeries)}, ZScores: z, Signals: signals, Score: maxScore}})
	}
	return anomalies
}

func series(rows []clickhouse.ServiceTelemetry, fn func(clickhouse.ServiceTelemetry) float64) []float64 { out := make([]float64, 0, len(rows)); for _, row := range rows { out = append(out, fn(row)) }; return out }
func mean(values []float64) float64 { if len(values) == 0 { return 0 }; total := 0.0; for _, v := range values { total += v }; return total / float64(len(values)) }
func zscore(current float64, values []float64) float64 { if len(values) == 0 { return 0 }; m := mean(values); variance := 0.0; for _, v := range values { variance += math.Pow(v-m, 2) }; sd := math.Sqrt(variance / float64(len(values))); if sd == 0 { if current == m { return 0 }; return 3 }; return (current - m) / sd }
