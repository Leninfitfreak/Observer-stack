package repository

import (
	"context"
	"database/sql"
	"encoding/json"
	"time"

	"github.com/google/uuid"
	_ "github.com/jackc/pgx/v5/stdlib"

	"ai_observer_core/internal/config"
	"ai_observer_core/internal/problem"
)

type ProblemRepository struct { db *sql.DB }

func New(cfg config.Config) (*ProblemRepository, error) {
	db, err := sql.Open("pgx", cfg.PostgresDSN())
	if err != nil { return nil, err }
	db.SetMaxOpenConns(10)
	db.SetMaxIdleConns(5)
	return &ProblemRepository{db: db}, nil
}

func (r *ProblemRepository) Close() error { return r.db.Close() }
func (r *ProblemRepository) Health(ctx context.Context) error { return r.db.PingContext(ctx) }
func NewProblemID() string { return uuid.NewString() }

func (r *ProblemRepository) Migrate(ctx context.Context) error {
	query := `CREATE TABLE IF NOT EXISTS problems (
		problem_id TEXT PRIMARY KEY,
		project_id TEXT NOT NULL,
		cluster TEXT NOT NULL,
		namespace TEXT NOT NULL,
		service TEXT NOT NULL,
		root_cause_entity TEXT NOT NULL,
		impacted_entities JSONB NOT NULL,
		severity TEXT NOT NULL,
		confidence DOUBLE PRECISION NOT NULL,
		causal_chain JSONB NOT NULL,
		correlated_signals JSONB NOT NULL,
		impact_assessment TEXT NOT NULL,
		recommended_actions JSONB NOT NULL,
		start_time TIMESTAMPTZ NOT NULL,
		end_time TIMESTAMPTZ NOT NULL,
		created_at TIMESTAMPTZ NOT NULL,
		anomaly_score DOUBLE PRECISION NOT NULL,
		metrics_summary JSONB NOT NULL,
		logs_summary JSONB NOT NULL,
		trace_summary JSONB NOT NULL
	);
	CREATE INDEX IF NOT EXISTS idx_problems_filters ON problems(project_id, cluster, namespace, service, created_at DESC);`
	_, err := r.db.ExecContext(ctx, query)
	return err
}

func (r *ProblemRepository) ExistsRecent(ctx context.Context, projectID, cluster, namespace, service string, start time.Time) (bool, error) {
	var exists bool
	err := r.db.QueryRowContext(ctx, `SELECT EXISTS(SELECT 1 FROM problems WHERE project_id=$1 AND cluster=$2 AND namespace=$3 AND service=$4 AND start_time >= $5)`, projectID, cluster, namespace, service, start.Add(-5*time.Minute)).Scan(&exists)
	return exists, err
}

func (r *ProblemRepository) Insert(ctx context.Context, p problem.Problem) error {
	impacted, _ := json.Marshal(p.ImpactedEntities)
	causal, _ := json.Marshal(p.CausalChain)
	correlated, _ := json.Marshal(p.CorrelatedSignals)
	actions, _ := json.Marshal(p.RecommendedActions)
	metrics, _ := json.Marshal(p.MetricsSummary)
	logs, _ := json.Marshal(p.LogsSummary)
	traces, _ := json.Marshal(p.TraceSummary)
	_, err := r.db.ExecContext(ctx, `INSERT INTO problems (problem_id, project_id, cluster, namespace, service, root_cause_entity, impacted_entities, severity, confidence, causal_chain, correlated_signals, impact_assessment, recommended_actions, start_time, end_time, created_at, anomaly_score, metrics_summary, logs_summary, trace_summary) VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9,$10::jsonb,$11::jsonb,$12,$13::jsonb,$14,$15,$16,$17,$18::jsonb,$19::jsonb,$20::jsonb)`, p.ProblemID, p.ProjectID, p.Cluster, p.Namespace, p.Service, p.RootCauseEntity, string(impacted), p.Severity, p.Confidence, string(causal), string(correlated), p.ImpactAssessment, string(actions), p.StartTime, p.EndTime, p.CreatedAt, p.AnomalyScore, string(metrics), string(logs), string(traces))
	return err
}

type Filters struct { ProjectID, Cluster, Namespace, Service string; From, To *time.Time }

func (r *ProblemRepository) List(ctx context.Context, f Filters) ([]problem.Problem, error) {
	rows, err := r.db.QueryContext(ctx, `SELECT problem_id, project_id, cluster, namespace, service, root_cause_entity, impacted_entities, severity, confidence, causal_chain, correlated_signals, impact_assessment, recommended_actions, start_time, end_time, created_at, anomaly_score, metrics_summary, logs_summary, trace_summary FROM problems WHERE ($1='' OR project_id=$1) AND ($2='' OR cluster=$2) AND ($3='' OR namespace=$3) AND ($4='' OR service=$4) AND ($5::timestamptz IS NULL OR created_at >= $5) AND ($6::timestamptz IS NULL OR created_at <= $6) ORDER BY created_at DESC LIMIT 200`, f.ProjectID, f.Cluster, f.Namespace, f.Service, f.From, f.To)
	if err != nil { return nil, err }
	defer rows.Close()
	out := make([]problem.Problem, 0)
	for rows.Next() { p, err := scanProblem(rows); if err != nil { return nil, err }; out = append(out, p) }
	return out, rows.Err()
}

func (r *ProblemRepository) Get(ctx context.Context, id string) (problem.Problem, error) {
	return scanProblem(r.db.QueryRowContext(ctx, `SELECT problem_id, project_id, cluster, namespace, service, root_cause_entity, impacted_entities, severity, confidence, causal_chain, correlated_signals, impact_assessment, recommended_actions, start_time, end_time, created_at, anomaly_score, metrics_summary, logs_summary, trace_summary FROM problems WHERE problem_id=$1`, id))
}

type scanner interface { Scan(dest ...any) error }

func scanProblem(s scanner) (problem.Problem, error) {
	var p problem.Problem
	var impacted, causal, correlated, actions, metrics, logs, traces []byte
	if err := s.Scan(&p.ProblemID, &p.ProjectID, &p.Cluster, &p.Namespace, &p.Service, &p.RootCauseEntity, &impacted, &p.Severity, &p.Confidence, &causal, &correlated, &p.ImpactAssessment, &actions, &p.StartTime, &p.EndTime, &p.CreatedAt, &p.AnomalyScore, &metrics, &logs, &traces); err != nil { return p, err }
	_ = json.Unmarshal(impacted, &p.ImpactedEntities)
	_ = json.Unmarshal(causal, &p.CausalChain)
	_ = json.Unmarshal(correlated, &p.CorrelatedSignals)
	_ = json.Unmarshal(actions, &p.RecommendedActions)
	_ = json.Unmarshal(metrics, &p.MetricsSummary)
	_ = json.Unmarshal(logs, &p.LogsSummary)
	_ = json.Unmarshal(traces, &p.TraceSummary)
	return p, nil
}
