package v2

import "context"

func (s *Service) DiscoverFilters(ctx context.Context, scope Scope) FilterOptions {
	options := FilterOptions{
		Clusters:   []string{},
		Namespaces: []string{},
		Services:   []string{},
	}
	if clusters, namespaces, services, err := s.api.fetchScopeFacets(ctx, scope); err == nil {
		options.Clusters = clusters
		options.Namespaces = namespaces
		options.Services = services
	}
	if services, err := s.api.fetchServices(ctx, Scope{
		Cluster:   scope.Cluster,
		Namespace: scope.Namespace,
		Start:     scope.Start,
		End:       scope.End,
	}); err == nil && len(services) > 0 {
		set := map[string]struct{}{}
		for _, item := range services {
			if item.ServiceName != "" {
				set[item.ServiceName] = struct{}{}
			}
		}
		options.Services = sortedKeys(set)
	}
	if len(options.Clusters) == 0 && scope.Cluster != "" {
		options.Clusters = []string{scope.Cluster}
	}
	if len(options.Namespaces) == 0 && scope.Namespace != "" {
		options.Namespaces = []string{scope.Namespace}
	}
	return options
}

