package clickhouse

import (
	"regexp"
	"strings"
)

var (
	podHashSuffixPattern    = regexp.MustCompile(`-[a-f0-9]{8,10}-[a-z0-9]{5}$`)
	deployHashSuffixPattern = regexp.MustCompile(`-[a-f0-9]{8,10}$`)
	infraTokenPattern       = regexp.MustCompile(`[^a-z0-9]+`)
)

func canonicalizeServiceName(value string) string {
	service := strings.ToLower(strings.TrimSpace(value))
	if service == "" {
		return ""
	}
	service = strings.TrimSuffix(service, ".svc.cluster.local")
	service = strings.TrimSuffix(service, ".svc")
	service = strings.TrimSuffix(service, ".cluster.local")
	service = strings.TrimSuffix(service, ".local")
	service = strings.TrimSpace(service)
	service = podHashSuffixPattern.ReplaceAllString(service, "")
	service = deployHashSuffixPattern.ReplaceAllString(service, "")
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
	return strings.ToLower(namespace)
}

func canonicalCluster(value string) string {
	cluster := strings.TrimSpace(value)
	return strings.ToLower(cluster)
}

func canonicalizeInfraToken(value string) string {
	token := strings.ToLower(strings.TrimSpace(value))
	if token == "" {
		return ""
	}
	token = strings.TrimPrefix(token, "persistent://")
	token = strings.TrimSuffix(token, ".svc.cluster.local")
	token = strings.TrimSuffix(token, ".svc")
	token = strings.TrimSuffix(token, ".cluster.local")
	token = strings.TrimSuffix(token, ".local")
	token = infraTokenPattern.ReplaceAllString(token, "-")
	token = strings.Trim(token, "-._/")
	return token
}

func CanonicalMessagingNodeID(system, destination string) string {
	normalizedSystem := firstNonEmpty(canonicalizeInfraToken(system), "broker")
	normalizedDestination := canonicalizeInfraToken(destination)
	if normalizedDestination == "" {
		return "messaging:" + normalizedSystem
	}
	return "messaging:" + normalizedSystem + "/" + normalizedDestination
}

func CanonicalDatabaseNodeID(system, name string) string {
	normalizedSystem := firstNonEmpty(canonicalizeInfraToken(system), "database")
	normalizedName := canonicalizeInfraToken(name)
	if normalizedName == "" {
		return "db:" + normalizedSystem
	}
	return "db:" + normalizedSystem + "/" + normalizedName
}

func InferTopologyNodeType(id string) string {
	value := strings.ToLower(strings.TrimSpace(id))
	switch {
	case strings.HasPrefix(value, "messaging:"):
		return "messaging"
	case strings.HasPrefix(value, "db:"):
		return "database"
	default:
		return "service"
	}
}

func CanonicalTopologyNodeID(value string) string {
	raw := strings.ToLower(strings.TrimSpace(value))
	switch {
	case raw == "":
		return ""
	case strings.HasPrefix(raw, "messaging:"):
		parts := strings.SplitN(strings.TrimPrefix(raw, "messaging:"), "/", 2)
		system := ""
		destination := ""
		if len(parts) > 0 {
			system = parts[0]
		}
		if len(parts) == 2 {
			destination = parts[1]
		}
		return CanonicalMessagingNodeID(system, destination)
	case strings.HasPrefix(raw, "topic:"):
		return CanonicalMessagingNodeID("broker", strings.TrimPrefix(raw, "topic:"))
	case strings.HasPrefix(raw, "queue:"):
		return CanonicalMessagingNodeID("broker", strings.TrimPrefix(raw, "queue:"))
	case strings.HasPrefix(raw, "db:"):
		parts := strings.SplitN(strings.TrimPrefix(raw, "db:"), "/", 2)
		system := ""
		name := ""
		if len(parts) > 0 {
			system = parts[0]
		}
		if len(parts) == 2 {
			name = parts[1]
		}
		return CanonicalDatabaseNodeID(system, name)
	case raw == "database":
		return CanonicalDatabaseNodeID(raw, "")
	default:
		return canonicalizeServiceName(raw)
	}
}
