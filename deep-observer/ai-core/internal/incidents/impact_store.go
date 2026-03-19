package incidents

import (
	"context"
	"math"
)

func (s *Store) ReplaceIncidentImpacts(ctx context.Context, incidentID string, impacts []IncidentImpact) error {
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)

	if _, err := tx.Exec(ctx, `DELETE FROM incident_impacts WHERE incident_id = $1`, incidentID); err != nil {
		return err
	}
	for _, impact := range impacts {
		if impact.Service == "" || impact.ImpactType == "" {
			continue
		}
		score := math.Max(0, impact.ImpactScore)
		if _, err := tx.Exec(ctx, `
			INSERT INTO incident_impacts (incident_id, service, impact_type, impact_score, created_at)
			VALUES ($1,$2,$3,$4,NOW())
			ON CONFLICT (incident_id, service, impact_type) DO UPDATE
			SET impact_score = EXCLUDED.impact_score, created_at = NOW()
		`, incidentID, impact.Service, impact.ImpactType, score); err != nil {
			return err
		}
	}
	return tx.Commit(ctx)
}

func (s *Store) attachIncidentImpacts(ctx context.Context, items []Incident) error {
	for idx := range items {
		impacts, err := s.loadIncidentImpacts(ctx, items[idx].ID)
		if err != nil {
			return err
		}
		items[idx].Impacts = impacts
	}
	return nil
}

func (s *Store) loadIncidentImpacts(ctx context.Context, incidentID string) ([]IncidentImpact, error) {
	rows, err := s.pool.Query(ctx, `
		SELECT incident_id, service, impact_type, impact_score
		FROM incident_impacts
		WHERE incident_id = $1
		ORDER BY impact_score DESC, service ASC
	`, incidentID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	impacts := make([]IncidentImpact, 0)
	for rows.Next() {
		var impact IncidentImpact
		if scanErr := rows.Scan(&impact.IncidentID, &impact.Service, &impact.ImpactType, &impact.ImpactScore); scanErr != nil {
			return nil, scanErr
		}
		impact.Service = normalizeIncidentEntity(impact.Service)
		impacts = append(impacts, impact)
	}
	return impacts, rows.Err()
}
