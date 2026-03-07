# Service Topology Discovery

## Objective
Build a runtime dependency graph from real telemetry, not static service lists.

## Data Source
ClickHouse trace table:
- `signoz_traces.distributed_signoz_index_v3`

## Discovery Logic
Implemented in `ai-core/internal/clickhouse/topology.go`:

1. **Node discovery**
   - Derive service name from span/service resource attributes.
   - Normalize names (remove pod hash suffixes).
   - Classify node types:
     - `service`
     - `messaging` (`kafka`)
     - `database` (`postgres`/`database`)

2. **Trace parent-child edges**
   - Join child span `parent_span_id` to parent `span_id` in same `trace_id`.
   - Infer dependency type:
     - `trace_http`
     - `trace_rpc`

3. **Kafka messaging edges**
   - Detect `messaging.system=kafka`.
   - Publish/send spans -> `service -> kafka`.
   - Process/receive spans -> `kafka -> service`.
   - Carry destination/topic metadata in edge payload.

4. **Database edges**
   - Detect `db.system` and `db.name`/server attrs.
   - Create `service -> postgres` (or generic `database`) edges.

5. **Sanitization and filtering**
   - Remove infrastructure/system noise services.
   - Keep only valid application service IDs and allowed external node types.
   - Deduplicate nodes and edges.

## Persistence
Topology is persisted into:
- `dependency_graphs` (graph snapshot)
- `service_dependencies` (edge rows with confidence/call/latency/error)
- `graph_nodes`/`graph_edges` (knowledge graph representation)

## External Services in Topology
Kafka and PostgreSQL can appear even when external to Kubernetes service registry because they are inferred from trace/messaging/db attributes.

