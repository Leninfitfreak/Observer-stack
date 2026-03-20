package clickhouse

import (
	"context"
	"fmt"
	"sort"
	"strings"
	"time"
)

type TopologyGraph struct {
	GeneratedAt time.Time      `json:"generated_at"`
	Nodes       []TopologyNode `json:"nodes"`
	Edges       []TopologyEdge `json:"edges"`
}

type TopologyNode struct {
	ID           string  `json:"id"`
	Label        string  `json:"label"`
	NodeType     string  `json:"node_type"`
	Cluster      string  `json:"cluster"`
	Namespace    string  `json:"namespace"`
	RequestCount int64   `json:"request_count"`
	ErrorRate    float64 `json:"error_rate"`
}

type TopologyEdge struct {
	Source         string  `json:"source"`
	Target         string  `json:"target"`
	DependencyType string  `json:"dependency_type,omitempty"`
	Destination    string  `json:"destination,omitempty"`
	CallCount      int64   `json:"call_count"`
	AvgLatencyMs   float64 `json:"avg_latency_ms"`
	ErrorRate      float64 `json:"error_rate"`
}

type TimelineEvent struct {
	Timestamp time.Time `json:"timestamp"`
	Kind      string    `json:"kind"`
	Severity  string    `json:"severity"`
	Entity    string    `json:"entity"`
	Title     string    `json:"title"`
	Details   string    `json:"details"`
	Value     float64   `json:"value,omitempty"`
}

func (c *Client) BuildTopology(ctx context.Context, filters Filters) (TopologyGraph, error) {
	graph := TopologyGraph{
		GeneratedAt: time.Now().UTC(),
		Nodes:       []TopologyNode{},
		Edges:       []TopologyEdge{},
	}

	nodeRows, err := c.conn.Query(ctx, fmt.Sprintf(`
		SELECT
			coalesce(
				nullIf(serviceName, ''),
				nullIf(resources_string['service.name'], ''),
				nullIf(resources_string['k8s.service.name'], ''),
				nullIf(resources_string['k8s.deployment.name'], '')
			) AS service,
			ifNull(nullIf(resources_string['k8s.namespace.name'], ''), '') AS namespace,
			ifNull(nullIf(resources_string['k8s.cluster.name'], ''), '') AS cluster,
			toInt64(count()) AS request_count,
			avg(toFloat64(hasError)) AS error_rate
		FROM %s
		WHERE %s
		GROUP BY service, namespace, cluster
		HAVING service != ''
		ORDER BY request_count DESC
		LIMIT 50
	`, tracesTable, traceWhere(filters)))
	if err != nil {
		return graph, err
	}
	defer nodeRows.Close()

	nodeMap := map[string]TopologyNode{}
	for nodeRows.Next() {
		var node TopologyNode
		if scanErr := nodeRows.Scan(&node.ID, &node.Namespace, &node.Cluster, &node.RequestCount, &node.ErrorRate); scanErr != nil {
			return graph, scanErr
		}
		node.ID = canonicalizeServiceName(node.ID)
		if ignoredService(node.ID) {
			continue
		}
		node.Label = node.ID
		node.NodeType = "service"
		nodeMap[node.ID] = node
	}
	if err := nodeRows.Err(); err != nil {
		return graph, err
	}

	edgeRows, err := c.conn.Query(ctx, fmt.Sprintf(`
		SELECT
			parent.source_service AS source,
			child.target_service AS target,
			if(max(length(child.rpc_system)) > 0 OR max(length(parent.rpc_system)) > 0, 'trace_rpc', 'trace_http') AS dependency_type,
			toInt64(count()) AS call_count,
			avg(child.duration_nano) / 1000000 AS avg_latency_ms,
			avg(toFloat64(child.has_error)) AS error_rate
		FROM (
			SELECT
				trace_id,
				parent_span_id,
				duration_nano,
				has_error,
				coalesce(
					nullIf(serviceName, ''),
					nullIf(resources_string['service.name'], ''),
					nullIf(resources_string['k8s.service.name'], ''),
					nullIf(resources_string['k8s.deployment.name'], '')
				) AS target_service,
				coalesce(attributes_string['rpc.system'], '') AS rpc_system
			FROM %s
			WHERE %s
		) AS child
		INNER JOIN (
			SELECT
				trace_id,
				span_id,
				coalesce(
					nullIf(serviceName, ''),
					nullIf(resources_string['service.name'], ''),
					nullIf(resources_string['k8s.service.name'], ''),
					nullIf(resources_string['k8s.deployment.name'], '')
				) AS source_service,
				coalesce(attributes_string['rpc.system'], '') AS rpc_system
			FROM %s
			WHERE %s
		) AS parent
			ON child.trace_id = parent.trace_id
			AND child.parent_span_id = parent.span_id
		WHERE child.target_service != ''
		  AND parent.source_service != ''
		  AND child.target_service != parent.source_service
		GROUP BY source, target
		ORDER BY call_count DESC
		LIMIT 100
	`, tracesTable, traceWhere(filters), tracesTable, traceWhere(filters)))
	if err != nil {
		return graph, err
	}
	defer edgeRows.Close()

	for edgeRows.Next() {
		var edge TopologyEdge
		if scanErr := edgeRows.Scan(&edge.Source, &edge.Target, &edge.DependencyType, &edge.CallCount, &edge.AvgLatencyMs, &edge.ErrorRate); scanErr != nil {
			return graph, scanErr
		}
		edge.Source = canonicalizeServiceName(edge.Source)
		edge.Target = canonicalizeServiceName(edge.Target)
		if ignoredService(edge.Source) || ignoredService(edge.Target) {
			continue
		}
		graph.Edges = append(graph.Edges, edge)
		if _, ok := nodeMap[edge.Source]; !ok {
			nodeMap[edge.Source] = TopologyNode{ID: edge.Source, Label: edge.Source, NodeType: "service", Cluster: filters.Cluster, Namespace: filters.Namespace}
		}
		if _, ok := nodeMap[edge.Target]; !ok {
			nodeMap[edge.Target] = TopologyNode{ID: edge.Target, Label: edge.Target, NodeType: "service", Cluster: filters.Cluster, Namespace: filters.Namespace}
		}
	}
	if err := edgeRows.Err(); err != nil {
		return graph, err
	}

	messagingEdges, err := c.messagingEdges(ctx, filters)
	if err != nil {
		return graph, err
	}
	addEdges := func(edges []TopologyEdge) {
		for _, edge := range edges {
			graph.Edges = append(graph.Edges, edge)
			if _, ok := nodeMap[edge.Source]; !ok {
				nodeMap[edge.Source] = TopologyNode{ID: edge.Source, Label: edge.Source, NodeType: classifyNodeType(edge.Source), Cluster: filters.Cluster, Namespace: filters.Namespace}
			}
			if _, ok := nodeMap[edge.Target]; !ok {
				nodeMap[edge.Target] = TopologyNode{ID: edge.Target, Label: edge.Target, NodeType: classifyNodeType(edge.Target), Cluster: filters.Cluster, Namespace: filters.Namespace}
			}
		}
	}
	addEdges(messagingEdges)
	databaseEdges, err := c.databaseEdges(ctx, filters)
	if err == nil {
		addEdges(databaseEdges)
	}

	dedup := make([]TopologyEdge, 0, len(graph.Edges))
	seen := map[string]struct{}{}
	for _, edge := range graph.Edges {
		key := edge.Source + "|" + edge.Target + "|" + edge.DependencyType + "|" + edge.Destination
		if _, ok := seen[key]; ok {
			continue
		}
		seen[key] = struct{}{}
		dedup = append(dedup, edge)
	}
	graph.Edges = dedup
	for _, node := range nodeMap {
		graph.Nodes = append(graph.Nodes, node)
	}
	sort.Slice(graph.Nodes, func(i, j int) bool {
		return graph.Nodes[i].ID < graph.Nodes[j].ID
	})
	return graph, nil
}

func (c *Client) messagingEdges(ctx context.Context, filters Filters) ([]TopologyEdge, error) {
	edges := []TopologyEdge{}
	query := fmt.Sprintf(`
		WITH publish AS (
			SELECT
				coalesce(
					nullIf(serviceName, ''),
					nullIf(resources_string['service.name'], ''),
					nullIf(resources_string['k8s.service.name'], ''),
					nullIf(resources_string['k8s.deployment.name'], '')
				) AS source,
				lowerUTF8(attributes_string['messaging.system']) AS messaging_system,
				coalesce(
					nullIf(attributes_string['messaging.destination.name'], ''),
					nullIf(attributes_string['messaging.destination'], ''),
					nullIf(attributes_string['messaging.destination_name'], '')
				) AS destination,
				toInt64(count()) AS call_count,
				avg(durationNano) / 1000000 AS avg_latency_ms,
				avg(toFloat64(hasError)) AS error_rate
			FROM %s
			WHERE %s
			  AND lowerUTF8(attributes_string['messaging.system']) != ''
			  AND coalesce(nullIf(attributes_string['messaging.destination.name'], ''), nullIf(attributes_string['messaging.destination'], ''), nullIf(attributes_string['messaging.destination_name'], '')) != ''
			  AND lowerUTF8(coalesce(attributes_string['messaging.operation'], attributes_string['messaging.operation.type'], '')) IN ('publish', 'send')
			GROUP BY source, messaging_system, destination
		)
		SELECT
			publish.source AS source,
			publish.messaging_system AS messaging_system,
			publish.destination AS destination,
			publish.call_count AS call_count,
			publish.avg_latency_ms AS avg_latency_ms,
			publish.error_rate AS error_rate
		FROM publish
		WHERE source != ''
		ORDER BY call_count DESC
		LIMIT 100
	`, tracesTable, traceWhere(filters))
	rows, err := c.conn.Query(ctx, query)
	if err != nil {
		return edges, err
	}
	defer rows.Close()
	for rows.Next() {
		var edge TopologyEdge
		var messagingSystem string
		if scanErr := rows.Scan(&edge.Source, &messagingSystem, &edge.Destination, &edge.CallCount, &edge.AvgLatencyMs, &edge.ErrorRate); scanErr != nil {
			return edges, scanErr
		}
		edge.Source = canonicalizeServiceName(edge.Source)
		edge.Destination = strings.TrimSpace(edge.Destination)
		if ignoredService(edge.Source) {
			continue
		}
		edge.Target = CanonicalMessagingNodeID(messagingSystem, edge.Destination)
		edge.DependencyType = "messaging"
		edges = append(edges, edge)
	}
	consumerQuery := fmt.Sprintf(`
		SELECT
			coalesce(
				nullIf(serviceName, ''),
				nullIf(resources_string['service.name'], ''),
				nullIf(resources_string['k8s.service.name'], ''),
				nullIf(resources_string['k8s.deployment.name'], '')
			) AS target,
			lowerUTF8(attributes_string['messaging.system']) AS messaging_system,
			coalesce(
				nullIf(attributes_string['messaging.destination.name'], ''),
				nullIf(attributes_string['messaging.destination'], ''),
				nullIf(attributes_string['messaging.destination_name'], '')
			) AS destination,
			toInt64(count()) AS call_count,
			avg(durationNano) / 1000000 AS avg_latency_ms,
			avg(toFloat64(hasError)) AS error_rate
		FROM %s
		WHERE %s
		  AND lowerUTF8(attributes_string['messaging.system']) != ''
		  AND lowerUTF8(coalesce(attributes_string['messaging.operation'], attributes_string['messaging.operation.type'], '')) IN ('process', 'receive')
		GROUP BY target, messaging_system, destination
		ORDER BY call_count DESC
		LIMIT 100
	`, tracesTable, traceWhere(filters))
	consumers, err := c.conn.Query(ctx, consumerQuery)
	if err != nil {
		return edges, nil
	}
	defer consumers.Close()
	for consumers.Next() {
		var target string
		var messagingSystem string
		var destination string
		var calls int64
		var avg, errRate float64
		if scanErr := consumers.Scan(&target, &messagingSystem, &destination, &calls, &avg, &errRate); scanErr != nil {
			continue
		}
		target = canonicalizeServiceName(target)
		source := CanonicalMessagingNodeID(messagingSystem, destination)
		if target == "" || ignoredService(target) || source == "" {
			continue
		}
		edges = append(edges, TopologyEdge{
			Source:         source,
			Target:         target,
			DependencyType: "messaging",
			CallCount:      calls,
			AvgLatencyMs:   avg,
			ErrorRate:      errRate,
		})
	}
	return edges, rows.Err()
}

func (c *Client) databaseEdges(ctx context.Context, filters Filters) ([]TopologyEdge, error) {
	edges := []TopologyEdge{}
	query := fmt.Sprintf(`
		SELECT
			coalesce(
				nullIf(serviceName, ''),
				nullIf(resources_string['service.name'], ''),
				nullIf(resources_string['k8s.service.name'], ''),
				nullIf(resources_string['k8s.deployment.name'], '')
			) AS source,
			lowerUTF8(coalesce(nullIf(attributes_string['db.system'], ''), 'database')) AS db_system,
			lowerUTF8(coalesce(nullIf(attributes_string['db.name'], ''), nullIf(attributes_string['server.address'], ''), 'database')) AS db_name,
			toInt64(count()) AS call_count,
			avg(durationNano) / 1000000 AS avg_latency_ms,
			avg(toFloat64(hasError)) AS error_rate
		FROM %s
		WHERE %s
		  AND attributes_string['db.system'] != ''
		GROUP BY source, db_system, db_name
		ORDER BY call_count DESC
		LIMIT 60
	`, tracesTable, traceWhere(filters))
	rows, err := c.conn.Query(ctx, query)
	if err != nil {
		return edges, err
	}
	defer rows.Close()
	for rows.Next() {
		var edge TopologyEdge
		var dbSystem string
		var dbName string
		if scanErr := rows.Scan(&edge.Source, &dbSystem, &dbName, &edge.CallCount, &edge.AvgLatencyMs, &edge.ErrorRate); scanErr != nil {
			return edges, scanErr
		}
		edge.Source = canonicalizeServiceName(edge.Source)
		edge.Target = CanonicalDatabaseNodeID(dbSystem, dbName)
		if ignoredService(edge.Source) {
			continue
		}
		edge.DependencyType = "database"
		edges = append(edges, edge)
	}
	return edges, rows.Err()
}

func (c *Client) BuildTimeline(ctx context.Context, filters Filters, center time.Time, window time.Duration) ([]TimelineEvent, error) {
	start := center.Add(-window)
	end := center.Add(window)
	timelineFilters := filters
	timelineFilters.Start = start
	timelineFilters.End = end

	events := []TimelineEvent{}

	traceRows, err := c.conn.Query(ctx, fmt.Sprintf(`
		SELECT
			timestamp,
			serviceName,
			name,
			durationNano / 1000000 AS duration_ms,
			hasError
		FROM %s
		WHERE %s
		ORDER BY duration_ms DESC
		LIMIT 15
	`, tracesTable, traceWhere(timelineFilters)))
	if err == nil {
		defer traceRows.Close()
		for traceRows.Next() {
			var timestamp time.Time
			var service, name string
			var duration float64
			var hasError bool
			if scanErr := traceRows.Scan(&timestamp, &service, &name, &duration, &hasError); scanErr == nil {
				service = canonicalizeServiceName(service)
				severity := "info"
				if hasError {
					severity = "high"
				}
				events = append(events, TimelineEvent{
					Timestamp: timestamp.UTC(),
					Kind:      "trace",
					Severity:  severity,
					Entity:    service,
					Title:     name,
					Details:   fmt.Sprintf("Span latency %.2f ms", duration),
					Value:     duration,
				})
			}
		}
	}

	logRows, err := c.conn.Query(ctx, fmt.Sprintf(`
		SELECT
			timestamp,
			resources_string['service.name'] AS service,
			substring(toString(body), 1, 240) AS body,
			severity_number
		FROM %s
		WHERE %s
		ORDER BY timestamp DESC
		LIMIT 20
	`, logsTable, logWhere(timelineFilters)))
	if err == nil {
		defer logRows.Close()
		for logRows.Next() {
			var timestampNs uint64
			var service, body string
			var severityNumber uint8
			if scanErr := logRows.Scan(&timestampNs, &service, &body, &severityNumber); scanErr == nil {
				service = canonicalizeServiceName(service)
				events = append(events, TimelineEvent{
					Timestamp: time.Unix(0, int64(timestampNs)).UTC(),
					Kind:      "log",
					Severity:  severityFromLogLevel(severityNumber),
					Entity:    service,
					Title:     "Log event",
					Details:   body,
				})
			}
		}
	}

	metricRows, err := c.conn.Query(ctx, fmt.Sprintf(`
		SELECT
			toDateTime(unix_milli / 1000) AS bucket,
			resource_attrs['service.name'] AS service,
			toInt64(count()) AS datapoints,
			groupArray(3)(metric_name) AS names
		FROM %s
		WHERE unix_milli >= %d
		  AND unix_milli < %d
		  AND (%s)
		  AND (%s)
		  AND (%s)
		GROUP BY bucket, service
		ORDER BY bucket DESC
		LIMIT 20
	`, metricsTable, start.UnixMilli(), end.UnixMilli(),
		matchMapExprOptional("resource_attrs", "k8s.cluster.name", filters.Cluster),
		matchMapExprOptional("resource_attrs", "k8s.namespace.name", filters.Namespace),
		matchMetricServiceExpr(filters.Service)))
	if err == nil {
		defer metricRows.Close()
		for metricRows.Next() {
			var bucket time.Time
			var service string
			var datapoints int64
			var names []string
			if scanErr := metricRows.Scan(&bucket, &service, &datapoints, &names); scanErr == nil {
				service = canonicalizeServiceName(service)
				events = append(events, TimelineEvent{
					Timestamp: bucket.UTC(),
					Kind:      "metric",
					Severity:  "info",
					Entity:    service,
					Title:     "Metric activity",
					Details:   fmt.Sprintf("%d datapoints across %v", datapoints, names),
					Value:     float64(datapoints),
				})
			}
		}
	}

	sort.Slice(events, func(i, j int) bool {
		return events[i].Timestamp.Before(events[j].Timestamp)
	})
	return events, nil
}

func severityFromLogLevel(level uint8) string {
	switch {
	case level >= 17:
		return "high"
	case level >= 13:
		return "medium"
	default:
		return "info"
	}
}

func classifyNodeType(id string) string {
	return InferTopologyNodeType(id)
}

func traceWhereWithAlias(alias string, filters Filters) string {
	resourceFilter := traceResourceFilterWithAlias(alias, filters)
	parts := []string{
		fmt.Sprintf("%s.timestamp >= toDateTime64(%d / 1000.0, 3)", alias, filters.Start.UnixMilli()),
		fmt.Sprintf("%s.timestamp < toDateTime64(%d / 1000.0, 3)", alias, filters.End.UnixMilli()),
		fmt.Sprintf("positionCaseInsensitive(%s.name, '/actuator/prometheus') = 0", alias),
		fmt.Sprintf("positionCaseInsensitive(%s.name, '/actuator/health') = 0", alias),
		fmt.Sprintf("positionCaseInsensitive(%s.attributes_string['http.route'], '/actuator/prometheus') = 0", alias),
		fmt.Sprintf("positionCaseInsensitive(%s.attributes_string['http.route'], '/actuator/health') = 0", alias),
	}
	if filters.Service != "" {
		parts = append(parts, fmt.Sprintf("replaceRegexpOne(replaceRegexpOne(lowerUTF8(coalesce(nullIf(%s.serviceName, ''), nullIf(%s.resources_string['service.name'], ''), nullIf(%s.resources_string['k8s.service.name'], ''), nullIf(%s.resources_string['k8s.deployment.name'], ''))), '-[a-f0-9]{8,10}-[a-z0-9]{5}$', ''), '-[a-f0-9]{8,10}$', '') = '%s'", alias, alias, alias, alias, escape(canonicalizeServiceName(filters.Service))))
	}
	if filters.Namespace != "" && resourceFilter == "" {
		parts = append(parts, fmt.Sprintf("%s.resources_string['k8s.namespace.name'] = '%s'", alias, escape(filters.Namespace)))
	}
	if filters.Cluster != "" && resourceFilter == "" {
		parts = append(parts, fmt.Sprintf("%s.resources_string['k8s.cluster.name'] = '%s'", alias, escape(filters.Cluster)))
	}
	if resourceFilter != "" {
		parts = append(parts, resourceFilter)
	}
	return strings.Join(parts, " AND ")
}

func traceResourceFilterWithAlias(alias string, filters Filters) string {
	subQuery := resourceFingerprintSubquery(tracesResTable, filters)
	if subQuery == "" {
		return ""
	}
	return fmt.Sprintf("%s.resource_fingerprint GLOBAL IN (%s)", alias, subQuery)
}
