package truth

import (
	"context"
	"sort"
	"time"

	"deep-observer/ai-core/internal/clickhouse"
	"deep-observer/ai-core/internal/incidents"
)

func (s *Service) DiscoverFilterOptions(ctx context.Context, scope NormalizedScope) FilterOptions {
	options := FilterOptions{
		Clusters:   []string{},
		Namespaces: []string{},
		Services:   []string{},
	}

	client, err := s.newClickHouseClient(ctx)
	if err != nil {
		return options
	}
	defer client.Close()

	lookback := scope.End.Sub(scope.Start)
	if lookback < time.Hour {
		lookback = 24 * time.Hour
	}

	selection := clickhouse.ServiceSelection{
		Cluster:   scope.Cluster,
		Namespace: scope.Namespace,
		Service:   scope.Service,
	}
	candidates, err := client.ListActiveServices(ctx, lookback, selection)
	if err == nil {
		clusterSet := map[string]struct{}{}
		namespaceSet := map[string]struct{}{}
		serviceSet := map[string]struct{}{}
		for _, candidate := range candidates {
			if candidate.Cluster != "" {
				clusterSet[candidate.Cluster] = struct{}{}
			}
			if candidate.Namespace != "" {
				namespaceSet[candidate.Namespace] = struct{}{}
			}
			if candidate.Service != "" {
				serviceSet[candidate.Service] = struct{}{}
			}
		}
		options.Clusters = sortedSet(clusterSet)
		options.Namespaces = sortedSet(namespaceSet)
		options.Services = sortedSet(serviceSet)
	}

	if len(options.Clusters) == 0 || len(options.Namespaces) == 0 || len(options.Services) == 0 {
		items, err := s.store.ListIncidents(ctx, incidents.QueryFilters{
			ProjectID: s.project.ProjectID,
			Cluster:   scope.Cluster,
			Namespace: scope.Namespace,
			Service:   scope.Service,
			Start:     &scope.Start,
			End:       &scope.End,
			Limit:     300,
		})
		if err == nil {
			clusterSet := map[string]struct{}{}
			namespaceSet := map[string]struct{}{}
			serviceSet := map[string]struct{}{}
			for _, item := range items {
				if item.Cluster != "" {
					clusterSet[item.Cluster] = struct{}{}
				}
				if item.Namespace != "" {
					namespaceSet[item.Namespace] = struct{}{}
				}
				if item.Service != "" {
					serviceSet[item.Service] = struct{}{}
				}
			}
			if len(options.Clusters) == 0 {
				options.Clusters = sortedSet(clusterSet)
			}
			if len(options.Namespaces) == 0 {
				options.Namespaces = sortedSet(namespaceSet)
			}
			if len(options.Services) == 0 {
				options.Services = sortedSet(serviceSet)
			}
		}
	}

	return options
}

func sortedSet(values map[string]struct{}) []string {
	out := make([]string, 0, len(values))
	for value := range values {
		if value != "" {
			out = append(out, value)
		}
	}
	sort.Strings(out)
	return out
}
