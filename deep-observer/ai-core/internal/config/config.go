package config

import (
	"bufio"
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"
)

type Config struct {
	APIPort         string
	Project         ProjectConfig
	Postgres        PostgresConfig
	ClickHouse      ClickHouseConfig
	Detector        DetectorConfig
	Alerts          AlertsConfig
	BrainServiceURL string
}

type ProjectConfig struct {
	ProjectID       string
	ClusterID       string
	NamespaceFilter string
	ServiceFilter   string
}

type PostgresConfig struct {
	Host     string
	Port     int
	User     string
	Password string
	Database string
}

type ClickHouseConfig struct {
	Host     string
	Port     int
	User     string
	Password string
	Database string
}

type DetectorConfig struct {
	Interval              time.Duration
	LookbackWindow        time.Duration
	BaselineWindow        time.Duration
	AnomalyThresholdZScore float64
}

type AlertsConfig struct {
	SlackWebhook string
	EmailTarget  string
	PagerDutyKey string
	WebhookURL   string
}

func Load(envPath string) (Config, error) {
	_ = loadFlexibleEnvFile(envPath)

	cfg := Config{
		APIPort: envString("AI_CORE_PORT", "8081"),
		Project: ProjectConfig{
			ProjectID:       envString("PROJECT_ID", "default-project"),
			ClusterID:       envString("CLUSTER_ID", ""),
			NamespaceFilter: envString("NAMESPACE_FILTER", ""),
			ServiceFilter:   envString("SERVICE_FILTER", ""),
		},
		Postgres: PostgresConfig{
			Host:     envString("POSTGRES_HOST", "localhost"),
			Port:     envInt("POSTGRES_PORT", 5432),
			User:     envString("POSTGRES_USER", "deep_observer"),
			Password: envString("POSTGRES_PASSWORD", "deep_observer"),
			Database: envString("POSTGRES_DB", "deep_observer"),
		},
		ClickHouse: ClickHouseConfig{
			Host:     envString("CLICKHOUSE_HOST", "localhost"),
			Port:     envInt("CLICKHOUSE_PORT", 9000),
			User:     firstNonEmpty(envString("CLICKHOUSE_USER", ""), envString("CLICKHOUSE_USERNAME", "default")),
			Password: envString("CLICKHOUSE_PASSWORD", ""),
			Database: envString("CLICKHOUSE_DATABASE", "default"),
		},
		Detector: DetectorConfig{
			Interval:               firstDuration(envDuration("INCIDENT_DETECTION_INTERVAL", 0), envDuration("DETECTOR_INTERVAL", time.Minute)),
			LookbackWindow:         firstDuration(minutesToDuration("LOOKBACK_MINUTES"), envDuration("LOOKBACK_WINDOW", 15*time.Minute)),
			BaselineWindow:         envDuration("BASELINE_WINDOW", 6*time.Hour),
			AnomalyThresholdZScore: envFloat("ANOMALY_THRESHOLD_ZSCORE", 2.5),
		},
		Alerts: AlertsConfig{
			SlackWebhook: envString("ALERT_SLACK_WEBHOOK", ""),
			EmailTarget:  envString("ALERT_EMAIL", ""),
			PagerDutyKey: envString("ALERT_PAGERDUTY_KEY", ""),
			WebhookURL:   envString("ALERT_WEBHOOK_URL", ""),
		},
		BrainServiceURL: envString("AI_BRAIN_URL", "http://ai-brain:8090"),
	}

	return cfg, nil
}

func loadFlexibleEnvFile(path string) error {
	file, err := os.Open(path)
	if err != nil {
		return err
	}
	defer file.Close()

	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		separator := "="
		if strings.Contains(line, ":") && !strings.Contains(line, "=") {
			separator = ":"
		}
		parts := strings.SplitN(line, separator, 2)
		if len(parts) != 2 {
			continue
		}
		key := strings.ToUpper(strings.TrimSpace(parts[0]))
		value := strings.Trim(strings.TrimSpace(parts[1]), "\"'")
		if key != "" && os.Getenv(key) == "" {
			_ = os.Setenv(key, value)
		}
	}
	return scanner.Err()
}

func envString(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}

func envInt(key string, fallback int) int {
	if value := os.Getenv(key); value != "" {
		if parsed, err := strconv.Atoi(value); err == nil {
			return parsed
		}
	}
	return fallback
}

func envDuration(key string, fallback time.Duration) time.Duration {
	if value := os.Getenv(key); value != "" {
		parsed, err := time.ParseDuration(value)
		if err == nil {
			return parsed
		}
	}
	return fallback
}

func envFloat(key string, fallback float64) float64 {
	if value := os.Getenv(key); value != "" {
		if parsed, err := strconv.ParseFloat(value, 64); err == nil {
			return parsed
		}
	}
	return fallback
}

func minutesToDuration(key string) time.Duration {
	if value := os.Getenv(key); value != "" {
		if parsed, err := strconv.Atoi(value); err == nil && parsed > 0 {
			return time.Duration(parsed) * time.Minute
		}
	}
	return 0
}

func firstDuration(values ...time.Duration) time.Duration {
	for _, value := range values {
		if value > 0 {
			return value
		}
	}
	return time.Minute
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if strings.TrimSpace(value) != "" {
			return value
		}
	}
	return ""
}

func (p PostgresConfig) DSN() string {
	return fmt.Sprintf("postgres://%s:%s@%s:%d/%s?sslmode=disable", p.User, p.Password, p.Host, p.Port, p.Database)
}
