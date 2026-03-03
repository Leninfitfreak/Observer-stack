package config

import (
	"fmt"
	"os"
	"strconv"
	"time"

	"github.com/joho/godotenv"
)

type Config struct {
	Port                     string
	ProjectID                string
	ClusterID                string
	NamespaceFilter          string
	ServiceFilter            string
	ClickHouseHost           string
	ClickHousePort           int
	ClickHouseUser           string
	ClickHousePassword       string
	PostgresHost             string
	PostgresPort             int
	PostgresUser             string
	PostgresPassword         string
	PostgresDB               string
	BrainURL                 string
	IncidentDetectionInterval time.Duration
	AnomalyThresholdZScore   float64
	LookbackMinutes          int
}

func Load() (Config, error) {
	_ = godotenv.Load("../.env")
	_ = godotenv.Load(".env")
	cfg := Config{
		Port: getEnv("AI_CORE_PORT", "8081"),
		ProjectID: getEnv("PROJECT_ID", "default-project"),
		ClusterID: getEnv("CLUSTER_ID", ""),
		NamespaceFilter: os.Getenv("NAMESPACE_FILTER"),
		ServiceFilter: os.Getenv("SERVICE_FILTER"),
		ClickHouseHost: getEnv("CLICKHOUSE_HOST", "signoz-clickhouse"),
		ClickHousePort: getEnvInt("CLICKHOUSE_PORT", 8123),
		ClickHouseUser: getEnv("CLICKHOUSE_USER", "default"),
		ClickHousePassword: os.Getenv("CLICKHOUSE_PASSWORD"),
		PostgresHost: getEnv("POSTGRES_HOST", "postgres"),
		PostgresPort: getEnvInt("POSTGRES_PORT", 5432),
		PostgresUser: getEnv("POSTGRES_USER", "ai_reasoning"),
		PostgresPassword: getEnv("POSTGRES_PASSWORD", "ai_reasoning"),
		PostgresDB: getEnv("POSTGRES_DB", "ai_reasoning"),
		BrainURL: getEnv("AI_BRAIN_URL", "http://ai-brain:8000"),
		IncidentDetectionInterval: time.Duration(getEnvInt("INCIDENT_DETECTION_INTERVAL", 60)) * time.Second,
		AnomalyThresholdZScore: getEnvFloat("ANOMALY_THRESHOLD_ZSCORE", 2.0),
		LookbackMinutes: getEnvInt("LOOKBACK_MINUTES", 30),
	}
	if cfg.ClusterID == "" { return cfg, fmt.Errorf("CLUSTER_ID is required") }
	if cfg.ProjectID == "" { return cfg, fmt.Errorf("PROJECT_ID is required") }
	return cfg, nil
}

func (c Config) PostgresDSN() string {
	return fmt.Sprintf("postgres://%s:%s@%s:%d/%s?sslmode=disable", c.PostgresUser, c.PostgresPassword, c.PostgresHost, c.PostgresPort, c.PostgresDB)
}

func getEnv(key, fallback string) string { if value := os.Getenv(key); value != "" { return value }; return fallback }
func getEnvInt(key string, fallback int) int { if value := os.Getenv(key); value != "" { if v, err := strconv.Atoi(value); err == nil { return v } }; return fallback }
func getEnvFloat(key string, fallback float64) float64 { if value := os.Getenv(key); value != "" { if v, err := strconv.ParseFloat(value, 64); err == nil { return v } }; return fallback }
