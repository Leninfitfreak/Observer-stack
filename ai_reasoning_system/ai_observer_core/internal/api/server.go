package api

import (
	"context"
	"log"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"

	"ai_observer_core/internal/brain"
	"ai_observer_core/internal/clickhouse"
	"ai_observer_core/internal/config"
	"ai_observer_core/internal/detector"
	"ai_observer_core/internal/problem"
	"ai_observer_core/internal/repository"
)

type Server struct {
	cfg      config.Config
	reader   *clickhouse.Reader
	repo     *repository.ProblemRepository
	brain    *brain.Client
	detector detector.Detector
}

func New(cfg config.Config, reader *clickhouse.Reader, repo *repository.ProblemRepository, brainClient *brain.Client) *Server {
	return &Server{cfg: cfg, reader: reader, repo: repo, brain: brainClient, detector: detector.Detector{Threshold: cfg.AnomalyThresholdZScore}}
}

func (s *Server) Engine() *gin.Engine {
	r := gin.Default()
	r.Use(func(c *gin.Context) {
		c.Writer.Header().Set("Access-Control-Allow-Origin", "*")
		c.Writer.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
		c.Writer.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization")
		if c.Request.Method == http.MethodOptions {
			c.AbortWithStatus(http.StatusNoContent)
			return
		}
		c.Next()
	})
	r.GET("/healthz", s.health)
	r.GET("/api/problems", s.listProblems)
	r.GET("/api/problems/:id", s.getProblem)
	r.POST("/api/detect/run", s.runDetection)
	return r
}

func (s *Server) StartScheduler(ctx context.Context) {
	ticker := time.NewTicker(s.cfg.IncidentDetectionInterval)
	go func() {
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				created, err := s.detectOnce(ctx)
				if err != nil { log.Printf("detect_failed err=%v", err) } else { log.Printf("detect_completed created=%d", created) }
			}
		}
	}()
}

func (s *Server) health(c *gin.Context) {
	ctx, cancel := context.WithTimeout(c.Request.Context(), 5*time.Second)
	defer cancel()
	c.JSON(http.StatusOK, gin.H{"status": "ok", "clickhouse": s.reader.Health(ctx) == nil, "postgres": s.repo.Health(ctx) == nil, "project_id": s.cfg.ProjectID, "cluster_id": s.cfg.ClusterID})
}

func (s *Server) runDetection(c *gin.Context) {
	created, err := s.detectOnce(c.Request.Context())
	if err != nil { c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()}); return }
	c.JSON(http.StatusOK, gin.H{"problems_created": created})
}

func (s *Server) detectOnce(ctx context.Context) (int, error) {
	rows, err := s.reader.FetchTelemetryWindow(ctx, s.cfg.LookbackMinutes)
	if err != nil { return 0, err }
	log.Printf("telemetry_window rows=%d lookback_minutes=%d", len(rows), s.cfg.LookbackMinutes)
	anomalies := s.detector.Detect(rows)
	log.Printf("anomaly_candidates count=%d", len(anomalies))
	created := 0
	for _, a := range anomalies {
		exists, err := s.repo.ExistsRecent(ctx, s.cfg.ProjectID, a.Cluster, a.Namespace, a.Service, a.Snapshot.Current.Timestamp)
		if err != nil { return created, err }
		if exists { continue }
		brainResp, err := s.brain.Reason(ctx, map[string]any{
			"project_id": s.cfg.ProjectID,
			"cluster": a.Cluster,
			"namespace": a.Namespace,
			"service": a.Service,
			"metrics_summary": map[string]any{"span_count": a.Snapshot.Current.SpanCount, "avg_latency_ms": a.Snapshot.Current.AvgLatencyMs, "error_count": a.Snapshot.Current.ErrorCount, "metric_count": a.Snapshot.Current.MetricCount},
			"logs_summary": map[string]any{"log_count": a.Snapshot.Current.LogCount},
			"trace_summary": map[string]any{"span_count": a.Snapshot.Current.SpanCount, "avg_latency_ms": a.Snapshot.Current.AvgLatencyMs},
			"anomaly_signals": a.Snapshot.Signals,
			"z_scores": a.Snapshot.ZScores,
			"baseline": a.Snapshot.Baseline,
		})
		if err != nil { return created, err }
		p := problem.Problem{
			ProblemID: repository.NewProblemID(),
			ProjectID: s.cfg.ProjectID,
			Cluster: a.Cluster,
			Namespace: a.Namespace,
			Service: a.Service,
			RootCauseEntity: brainResp.RootCauseEntity,
			ImpactedEntities: brainResp.ImpactedEntities,
			Severity: brainResp.Severity,
			Confidence: brainResp.Confidence,
			CausalChain: brainResp.CausalChain,
			CorrelatedSignals: brainResp.CorrelatedSignals,
			ImpactAssessment: brainResp.ImpactAssessment,
			RecommendedActions: brainResp.RecommendedActions,
			StartTime: a.Snapshot.Current.Timestamp,
			EndTime: a.Snapshot.Current.Timestamp,
			CreatedAt: time.Now().UTC(),
			AnomalyScore: a.Snapshot.Score,
			MetricsSummary: map[string]any{"current": a.Snapshot.Current, "baseline": a.Snapshot.Baseline, "z_scores": a.Snapshot.ZScores},
			LogsSummary: map[string]any{"log_count": a.Snapshot.Current.LogCount},
			TraceSummary: map[string]any{"span_count": a.Snapshot.Current.SpanCount, "avg_latency_ms": a.Snapshot.Current.AvgLatencyMs, "error_count": a.Snapshot.Current.ErrorCount},
		}
		if p.RootCauseEntity == "" { p.RootCauseEntity = a.Service }
		if len(p.ImpactedEntities) == 0 { p.ImpactedEntities = []string{a.Service} }
		if err := s.repo.Insert(ctx, p); err != nil { return created, err }
		created++
	}
	return created, nil
}

func (s *Server) listProblems(c *gin.Context) {
	var fromPtr, toPtr *time.Time
	if v := c.Query("from"); v != "" { if t, err := time.Parse(time.RFC3339, v); err == nil { fromPtr = &t } }
	if v := c.Query("to"); v != "" { if t, err := time.Parse(time.RFC3339, v); err == nil { toPtr = &t } }
	rows, err := s.repo.List(c.Request.Context(), repository.Filters{ProjectID: orDefault(c.Query("project_id"), s.cfg.ProjectID), Cluster: c.Query("cluster"), Namespace: c.Query("namespace"), Service: c.Query("service"), From: fromPtr, To: toPtr})
	if err != nil { c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()}); return }
	c.JSON(http.StatusOK, rows)
}

func (s *Server) getProblem(c *gin.Context) {
	row, err := s.repo.Get(c.Request.Context(), c.Param("id"))
	if err != nil { c.JSON(http.StatusNotFound, gin.H{"error": "problem not found"}); return }
	c.JSON(http.StatusOK, row)
}

func orDefault(value, fallback string) string { if value != "" { return value }; return fallback }
