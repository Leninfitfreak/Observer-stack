package truth

import (
	"context"
	"sort"
)

func (s *Service) DiscoverFilterOptions(ctx context.Context, scope NormalizedScope) FilterOptions {
	options := FilterOptions{
		Clusters:   []string{},
		Namespaces: []string{},
		Services:   []string{},
	}

	if clusters, namespaces, services, err := s.signozFetchScopeFacets(ctx, scope); err == nil {
		options.Clusters = clusters
		options.Namespaces = namespaces
		options.Services = services
	}

	services, err := s.signozFetchServices(ctx, NormalizedScope{
		Cluster:   scope.Cluster,
		Namespace: scope.Namespace,
		Service:   "",
		Start:     scope.Start,
		End:       scope.End,
	})
	if err != nil {
		return options
	}
	serviceSet := map[string]struct{}{}
	for _, svc := range services {
		if normalized := normalizeServiceName(svc.ServiceName); normalized != "" {
			serviceSet[normalized] = struct{}{}
		}
	}
	if len(serviceSet) > 0 {
		options.Services = sortedSet(serviceSet)
	}
	if len(options.Clusters) == 0 && scope.Cluster != "" {
		options.Clusters = []string{scope.Cluster}
	}
	if len(options.Namespaces) == 0 && scope.Namespace != "" {
		options.Namespaces = []string{scope.Namespace}
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
