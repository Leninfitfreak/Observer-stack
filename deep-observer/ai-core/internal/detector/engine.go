package detector

import (
	"context"
	"log"
	"math"
	"strconv"
	"time"

	"github.com/google/uuid"

	"deep-observer/ai-core/internal/clickhouse"
	"deep-observer/ai-core/internal/config"
	"deep-observer/ai-core/internal/enterprise"
	"deep-observer/ai-core/internal/incidents"
	"deep-observer/ai-core/internal/state"
)

type Engine struct {
	store           *incidents.Store
	chConfig        config.ClickHouseConfig
	project         config.ProjectConfig
	alerts          config.AlertsConfig
	interval        time.Duration
	lookback        time.Duration
	baseline        time.Duration
	zscoreThreshold float64
	causal          *enterprise.CausalGraphEngine
	slo             *enterprise.SLOEngine
	state           *state.Engine
}

func NewEngine(store *incidents.Store, chConfig config.ClickHouseConfig, project config.ProjectConfig, alerts config.AlertsConfig, cfg config.DetectorConfig) *Engine {
	return &Engine{
		store:           store,
		chConfig:        chConfig,
		project:         project,
		alerts:          alerts,
		interval:        cfg.Interval,
		lookback:        cfg.LookbackWindow,
		baseline:        cfg.BaselineWindow,
		zscoreThreshold: cfg.AnomalyThresholdZScore,
		causal:          enterprise.NewCausalGraphEngine(),
		slo:             enterprise.NewSLOEngine(store),
		state:           state.NewEngine(store),
	}
}

func (e *Engine) Run(ctx context.Context) {
	ticker := time.NewTicker(e.interval)
	defer ticker.Stop()

	e.runOnce(ctx)
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			e.runOnce(ctx)
		}
	}
}

func (e *Engine) runOnce(ctx context.Context) {
	client, err := clickhouse.NewClient(ctx, e.chConfig)
	if err != nil {
		log.Printf("detector connect clickhouse: %v", err)
		return
	}
	defer client.Close()

	services, err := client.ListActiveServices(ctx, e.lookback, clickhouse.ServiceSelection{
		Cluster:   e.project.ClusterID,
		Namespace: e.project.NamespaceFilter,
		Service:   e.project.ServiceFilter,
	})
	if err != nil {
		log.Printf("detector list services: %v", err)
		return
	}

	end := time.Now().UTC()
	start := end.Add(-e.lookback)
	topoCache := map[string]clickhouse.TopologyGraph{}
	problemByService := map[string]string{}
	for _, svc := range services {
		filters := clickhouse.Filters{
			Cluster:   svc.Cluster,
			Namespace: svc.Namespace,
			Service:   svc.Service,
			Start:     start,
			End:       end,
		}
		snapshot, err := client.ReadSnapshot(ctx, filters, e.baseline)
		if err != nil {
			log.Printf("detector snapshot %s: %v", svc.Service, err)
			continue
		}
		telemetrySources := []string{"traces"}
		if snapshot.LogCount > 0 {
			telemetrySources = append(telemetrySources, "logs")
		}
		if len(snapshot.MetricHighlights) > 0 {
			telemetrySources = append(telemetrySources, "metrics")
		}
		_ = e.store.UpsertServiceRegistryTyped(ctx, e.project.ProjectID, svc.Cluster, svc.Namespace, svc.Service, "service", telemetrySources)
		_ = e.slo.EnsureDefaults(ctx, svc.Service)

		adaptiveSignals, adaptiveErr := e.store.DetectAdaptiveSignals(ctx, e.project.ProjectID, svc.Cluster, svc.Namespace, svc.Service, snapshot)
		if adaptiveErr != nil {
			log.Printf("detector adaptive signals %s: %v", svc.Service, adaptiveErr)
		}
		incident, ok := evaluate(snapshot, e.zscoreThreshold)
		if len(adaptiveSignals) > 0 {
			if !ok {
				incident = incidents.Incident{
					Severity:     "medium",
					AnomalyScore: 30,
					Signals:      []string{},
				}
				ok = true
			}
			incident.Signals = append(incident.Signals, adaptiveSignals...)
			incident.AnomalyScore = math.Min(99, incident.AnomalyScore+float64(len(adaptiveSignals))*6)
			if incident.AnomalyScore >= 40 && incident.Severity == "medium" {
				incident.Severity = "high"
			}
		}
		_ = e.store.UpdateAdaptiveBaselines(ctx, e.project.ProjectID, svc.Cluster, svc.Namespace, svc.Service, snapshot)
		if !ok {
			log.Printf("detector no anomaly service=%s cluster=%s namespace=%s req=%d p95=%.2f err=%.4f", svc.Service, svc.Cluster, svc.Namespace, snapshot.RequestCount, snapshot.P95LatencyMs, snapshot.ErrorRate)
			continue
		}
		incident.ID = uuid.NewString()
		incident.ProjectID = e.project.ProjectID
		incident.Cluster = svc.Cluster
		incident.Namespace = svc.Namespace
		incident.Service = svc.Service
		incident.Timestamp = snapshot.ObservedAt
		incident.ProblemID = problemID(svc.Cluster, svc.Namespace, end)
		incident.TelemetrySnapshot = snapshot
		incident.RootCauseEntity = svc.Service

		cacheKey := svc.Cluster + "|" + svc.Namespace
		graph, ok := topoCache[cacheKey]
		if !ok {
			graph, err = client.BuildTopology(ctx, clickhouse.Filters{
				Cluster:   svc.Cluster,
				Namespace: svc.Namespace,
				Start:     start,
				End:       end,
			})
			if err == nil {
				topoCache[cacheKey] = graph
				_ = e.store.UpsertDependencyGraph(ctx, svc.Cluster, svc.Namespace, graph)
				_ = e.store.ReplaceServiceDependencies(ctx, e.project.ProjectID, svc.Cluster, svc.Namespace, graph.Edges)
				_ = e.store.UpsertSystemGraph(ctx, e.project.ProjectID, svc.Cluster, svc.Namespace, graph)
			}
		}
		neighbors := neighboringServices(graph, svc.Service)
		if len(neighbors) > 0 {
			incident.DependencyChain = neighbors
			incident.AnomalyScore = math.Min(99, incident.AnomalyScore+float64(len(neighbors))*4)
			if incident.AnomalyScore >= 40 && incident.Severity == "medium" {
				incident.Severity = "high"
			}
		}
		ranks := e.causal.Rank(incident, graph)
		if len(ranks) > 0 && ranks[0].Service != "" {
			incident.RootCauseEntity = ranks[0].Service
		}
		impacts := propagateIncidentImpacts(incident.RootCauseEntity, graph)
		if len(impacts) > 0 {
			chain := make([]string, 0, len(impacts))
			for _, impact := range impacts {
				if impact.Service == incident.RootCauseEntity {
					continue
				}
				chain = append(chain, impact.Service)
			}
			if len(chain) > 0 {
				incident.DependencyChain = chain
			}
		}
		_ = e.state.Record(ctx, e.project.ProjectID, snapshot, svc.Service, float64(len(neighbors))*10)

		incident.ProblemID = problemID(svc.Cluster, svc.Namespace, end)
		for _, neighbor := range neighbors {
			if existingProblem, has := problemByService[neighbor]; has {
				incident.ProblemID = existingProblem
				break
			}
		}
		problemByService[svc.Service] = incident.ProblemID

		timeline, err := client.BuildTimeline(ctx, filters, end, 5*time.Minute)
		if err == nil {
			incident.TimelineSummary = timeline
		}

		exists, err := e.store.HasRecentIncident(ctx, incident.Cluster, incident.Namespace, incident.Service, 15*time.Minute)
		if err != nil {
			log.Printf("detector check incident: %v", err)
			continue
		}
		if exists {
			log.Printf("detector skip duplicate service=%s cluster=%s namespace=%s", incident.Service, incident.Cluster, incident.Namespace)
			continue
		}
		if err := e.store.InsertIncident(ctx, incident); err != nil {
			log.Printf("detector insert incident: %v", err)
			continue
		}
		if err := e.store.ReplaceIncidentImpacts(ctx, incident.ID, impacts); err != nil {
			log.Printf("detector upsert incident impacts: %v", err)
		}
		problem := buildProblemFromRanks(incident, ranks)
		changeIDs, _ := e.correlateChanges(ctx, incident)
		problem.ChangeIDs = changeIDs
		if err := e.store.UpsertProblem(ctx, problem); err != nil {
			log.Printf("detector upsert problem: %v", err)
		}
		if err := e.store.UpsertIncidentKnowledgeGraph(ctx, incident); err != nil {
			log.Printf("detector upsert incident graph: %v", err)
		}
		e.queueAlerts(ctx, problem, incident)
		log.Printf("detector incident created id=%s service=%s score=%.2f signals=%v", incident.ID, incident.Service, incident.AnomalyScore, incident.Signals)
	}
}

func propagateIncidentImpacts(root string, graph clickhouse.TopologyGraph) []incidents.IncidentImpact {
	if root == "" {
		return nil
	}
	impacts := []incidents.IncidentImpact{{
		Service:    root,
		ImpactType: "root",
		ImpactScore: 1.0,
	}}

	upstream := map[string][]string{}
	downstream := map[string][]string{}
	for _, edge := range graph.Edges {
		if edge.Source == "" || edge.Target == "" {
			continue
		}
		downstream[edge.Source] = append(downstream[edge.Source], edge.Target)
		upstream[edge.Target] = append(upstream[edge.Target], edge.Source)
	}

	appendTraversal := func(neighbors map[string][]string, impactType string, depthPenalty float64) {
		type node struct {
			service string
			depth   int
		}
		queue := []node{{service: root, depth: 0}}
		seen := map[string]struct{}{root: {}}
		for len(queue) > 0 {
			current := queue[0]
			queue = queue[1:]
			for _, next := range neighbors[current.service] {
				if next == "" {
					continue
				}
				if _, ok := seen[next]; ok {
					continue
				}
				seen[next] = struct{}{}
				depth := current.depth + 1
				score := 1.0 / (1.0 + float64(depth)*depthPenalty)
				impacts = append(impacts, incidents.IncidentImpact{
					Service:    next,
					ImpactType: impactType,
					ImpactScore: score,
				})
				queue = append(queue, node{service: next, depth: depth})
			}
		}
	}
	appendTraversal(upstream, "upstream", 0.5)
	appendTraversal(downstream, "downstream", 0.35)
	return impacts
}

func (e *Engine) queueAlerts(ctx context.Context, problem incidents.Problem, incident incidents.Incident) {
	payload := map[string]any{
		"problem_id":  problem.ProblemID,
		"incident_id": incident.ID,
		"service":     incident.Service,
		"severity":    incident.Severity,
		"score":       incident.AnomalyScore,
	}
	_ = e.store.QueueProblemAlert(ctx, problem.ProblemID, "slack", e.alerts.SlackWebhook, payload)
	_ = e.store.QueueProblemAlert(ctx, problem.ProblemID, "email", e.alerts.EmailTarget, payload)
	_ = e.store.QueueProblemAlert(ctx, problem.ProblemID, "pagerduty", e.alerts.PagerDutyKey, payload)
	_ = e.store.QueueProblemAlert(ctx, problem.ProblemID, "webhook", e.alerts.WebhookURL, payload)
}

func buildProblemFromRanks(incident incidents.Incident, ranks []enterprise.RankedNode) incidents.Problem {
	root := incident.Service
	affected := []string{incident.Service}
	confidence := 0.7
	if len(ranks) > 0 {
		root = ranks[0].Service
		affected = make([]string, 0, len(ranks))
		for _, rank := range ranks {
			affected = append(affected, rank.Service)
		}
		confidence = math.Min(0.99, 0.6+(ranks[0].ImpactScore/150))
	}
	return incidents.Problem{
		ProblemID:        incident.ProblemID,
		ProjectID:        incident.ProjectID,
		Cluster:          incident.Cluster,
		Namespace:        incident.Namespace,
		RootCauseService: root,
		AffectedServices: affected,
		IncidentIDs:      []string{incident.ID},
		Confidence:       math.Round(confidence*100) / 100,
		CreatedAt:        incident.Timestamp,
	}
}

func (e *Engine) correlateChanges(ctx context.Context, incident incidents.Incident) ([]string, error) {
	changes, err := e.store.ListSystemChanges(ctx, firstNonEmpty(incident.Cluster, e.project.ClusterID), incident.Namespace, 200)
	if err != nil {
		return nil, err
	}
	changeIDs := []string{}
	window := 20 * time.Minute
	for _, change := range changes {
		if change.Timestamp.Before(incident.Timestamp.Add(-window)) || change.Timestamp.After(incident.Timestamp.Add(window)) {
			continue
		}
		changeIDs = append(changeIDs, change.ChangeID)
		if len(changeIDs) >= 10 {
			break
		}
	}
	return changeIDs, nil
}

func neighboringServices(graph clickhouse.TopologyGraph, service string) []string {
	if service == "" {
		return []string{}
	}
	neighbors := []string{}
	seen := map[string]struct{}{service: {}}
	for _, edge := range graph.Edges {
		if edge.Source == service && edge.Target != "" {
			if _, ok := seen[edge.Target]; !ok {
				neighbors = append(neighbors, edge.Target)
				seen[edge.Target] = struct{}{}
			}
		}
		if edge.Target == service && edge.Source != "" {
			if _, ok := seen[edge.Source]; !ok {
				neighbors = append(neighbors, edge.Source)
				seen[edge.Source] = struct{}{}
			}
		}
	}
	return neighbors
}

func problemID(cluster, namespace string, timestamp time.Time) string {
	return cluster + ":" + namespace + ":" + strconv.FormatInt(timestamp.Truncate(5*time.Minute).Unix(), 10)
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if value != "" {
			return value
		}
	}
	return ""
}

func evaluate(snapshot clickhouse.Snapshot, zscoreThreshold float64) (incidents.Incident, bool) {
	signals := []string{}
	score := 0.0

	if snapshot.RequestCount >= 30 && snapshot.P95LatencyMs >= 20 {
		signals = append(signals, "latency_spike")
		score += math.Min(30, snapshot.P95LatencyMs/2)
	} else if snapshot.BaselineLatencyMs > 0 && snapshot.P95LatencyMs > snapshot.BaselineLatencyMs*2 {
		signals = append(signals, "latency_spike")
		score += math.Min(35, (snapshot.P95LatencyMs/snapshot.BaselineLatencyMs)*10)
	}
	if snapshot.ErrorRate > math.Max(0.05, snapshot.BaselineErrorRate*2) {
		signals = append(signals, "error_rate_increase")
		score += math.Min(30, snapshot.ErrorRate*100)
	}
	if snapshot.CPUUtilization >= 0.85 || snapshot.CPUUtilization >= 85 {
		signals = append(signals, "cpu_saturation")
		score += 15
	}
	if snapshot.MemoryUtilization >= 0.85 || snapshot.MemoryUtilization >= 85 {
		signals = append(signals, "memory_pressure")
		score += 15
	}
	if snapshot.BaselineLatencyMs > 0 && math.Abs(snapshot.AvgLatencyMs-snapshot.BaselineLatencyMs) > snapshot.BaselineLatencyMs*0.5 {
		signals = append(signals, "baseline_deviation")
		score += 10
	}
	if len(snapshot.ErrorLogs) >= 3 {
		signals = append(signals, "log_anomaly")
		score += 25
	}
	if snapshot.LatencyZScore >= zscoreThreshold {
		signals = append(signals, "latency_zscore_deviation")
		score += math.Min(35, snapshot.LatencyZScore*8)
	}
	if len(signals) == 0 {
		return incidents.Incident{}, false
	}

	severity := "medium"
	switch {
	case score >= 60:
		severity = "critical"
	case score >= 40:
		severity = "high"
	}

	return incidents.Incident{
		Severity:     severity,
		AnomalyScore: math.Round(score*100) / 100,
		Signals:      signals,
	}, true
}
