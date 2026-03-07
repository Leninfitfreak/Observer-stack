package clickhouse

import (
	"regexp"
	"strings"
)

var (
	podHashSuffixPattern    = regexp.MustCompile(`-[a-f0-9]{8,10}-[a-z0-9]{5}$`)
	deployHashSuffixPattern = regexp.MustCompile(`-[a-f0-9]{8,10}$`)
	envSuffixPattern        = regexp.MustCompile(`-(dev|prod|staging|stage|qa|test)$`)
)

func canonicalizeServiceName(value string) string {
	service := strings.ToLower(strings.TrimSpace(value))
	if service == "" {
		return ""
	}
	for _, prefix := range []string{"dev-", "prod-", "staging-", "stage-", "qa-", "test-"} {
		if strings.HasPrefix(service, prefix) {
			service = strings.TrimPrefix(service, prefix)
			break
		}
	}
	if strings.HasPrefix(service, "leninkart-") {
		service = strings.TrimPrefix(service, "leninkart-")
	}
	service = strings.TrimSuffix(service, ".svc.cluster.local")
	service = strings.TrimSuffix(service, ".svc")
	service = strings.TrimSuffix(service, ".cluster.local")
	service = strings.TrimSuffix(service, ".local")
	service = strings.TrimSpace(service)
	service = podHashSuffixPattern.ReplaceAllString(service, "")
	service = deployHashSuffixPattern.ReplaceAllString(service, "")
	service = envSuffixPattern.ReplaceAllString(service, "")
	parts := strings.Split(service, "-")
	if len(parts) > 1 && len(parts)%2 == 0 {
		mid := len(parts) / 2
		left := strings.Join(parts[:mid], "-")
		right := strings.Join(parts[mid:], "-")
		if left == right {
			service = left
		}
	}
	service = strings.Trim(service, "-._")
	return service
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if strings.TrimSpace(value) != "" {
			return value
		}
	}
	return ""
}

func canonicalNamespace(value string) string {
	namespace := strings.TrimSpace(value)
	if namespace == "" {
		return "default"
	}
	return strings.ToLower(namespace)
}

func canonicalCluster(value string) string {
	cluster := strings.TrimSpace(value)
	if cluster == "" {
		return "default-cluster"
	}
	return strings.ToLower(cluster)
}
