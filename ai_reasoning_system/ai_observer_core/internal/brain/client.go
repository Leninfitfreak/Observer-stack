package brain

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"time"
)

type Client struct { baseURL string; http *http.Client }

type Response struct {
	RootCause          string   `json:"root_cause"`
	Confidence         float64  `json:"confidence"`
	CausalChain        []string `json:"causal_chain"`
	CorrelatedSignals  []string `json:"correlated_signals"`
	ImpactAssessment   string   `json:"impact_assessment"`
	RecommendedActions []string `json:"recommended_actions"`
	Severity           string   `json:"severity"`
	RootCauseEntity    string   `json:"root_cause_entity"`
	ImpactedEntities   []string `json:"impacted_entities"`
}

func New(baseURL string) *Client { return &Client{baseURL: baseURL, http: &http.Client{Timeout: 125 * time.Second}} }

func (c *Client) Reason(ctx context.Context, payload map[string]any) (Response, error) {
	body, _ := json.Marshal(payload)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+"/reason", bytes.NewReader(body))
	if err != nil { return Response{}, err }
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.http.Do(req)
	if err != nil { return Response{}, err }
	defer resp.Body.Close()
	if resp.StatusCode >= 300 { return Response{}, fmt.Errorf("brain returned status %d", resp.StatusCode) }
	var out Response
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil { return Response{}, err }
	return out, nil
}
