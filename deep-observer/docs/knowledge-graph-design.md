# Incident and System Knowledge Graph Design

## Goals
- Preserve causal context beyond single incidents.
- Reuse learned patterns for faster and more consistent root-cause reasoning.

## System Graph
Tables:
- `graph_nodes`
- `graph_edges`

Node types include:
- `service`
- `database`
- `kafka_topic`
- `deployment`
- `pod`
- `node`

Edge examples:
- `depends_on`
- `publishes_to`
- `connects_to`

Data source:
- Topology graph produced from traces/messaging/database spans.

## Incident Graph
Tables:
- `incident_graph_nodes`
- `incident_graph_edges`

Nodes:
- incident node (`incident:{id}`)
- service/dependency nodes
- signal nodes

Edges:
- `triggered_by`
- `impacts`
- `correlates_with`

## Incident Impact Graph
Table:
- `incident_impacts`

Fields:
- `incident_id`
- `service`
- `impact_type` (`root`, `upstream`, `downstream`)
- `impact_score`

Used by:
- incident filtering
- impacted-services rendering in dashboard
- future causal weighting enhancements

