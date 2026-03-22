# Runtime Stabilization Report

## Scope

This stabilization pass was limited to runtime safety and responsiveness. It did not redesign the SigNoz bootstrap, alerting, or dashboard definitions.

## Official SigNoz Baseline

Official references used:

- `https://raw.githubusercontent.com/SigNoz/signoz/v0.113.0/deploy/docker/docker-compose.yaml`
- `https://raw.githubusercontent.com/SigNoz/signoz/v0.113.0/deploy/docker/otel-collector-config.yaml`
- `https://signoz.io/docs/install/docker`

Comparison against the local `observer-stack`:

- The local `observer-stack/deploy/docker/docker-compose.yaml` matches the official `v0.113.0` compose layout for `clickhouse`, `signoz`, `otel-collector`, `zookeeper-1`, and the migrator.
- The local `observer-stack/deploy/docker/otel-collector-config.yaml` matches the official `v0.113.0` collector config except for one local addition:
  - an extra `prometheus/kafka` receiver and `metrics/prometheus-kafka` pipeline
- One more local deviation exists in the SigNoz UI container:
  - `../../frontend/build:/etc/signoz/web:ro`

These deviations were documented but not changed in this stabilization step because the runtime evidence pointed to a different primary bottleneck.

## Runtime Evidence Before Changes

Measured before the fix:

- `kafka-platform` health: `unhealthy`
- Kafka healthcheck failure mode: `Health check exceeded timeout (5s)`
- Kafka healthcheck command runtime when run manually: about `17.70s`
- `kafka-platform` runtime sample: about `336.90% CPU`, `1.067GiB` memory, `2976` PIDs
- Kafka process inspection showed many `[java] <defunct>` processes adopted by PID 1
- `signoz-clickhouse` runtime sample: between about `344.90%` and `517.40% CPU`
- `signoz-otel-collector` runtime sample: between about `58.66%` and `75.90% CPU`
- Authenticated SigNoz API timings:
  - `/api/v1/health`: about `2.662s`
  - `/api/v1/dashboards`: about `1.737s`
  - `/api/v1/dashboards/{generated}`: about `7.513s`

ClickHouse query evidence:

- In the last 10 minutes, `Insert` queries dominated `system.query_log`:
  - `4101` inserts
  - `517` selects
- Average select latency was only about `0.16s`, while the slowest work was insert-heavy.
- The longest recent queries were inserts into:
  - `signoz_logs.distributed_tag_attributes_v2`
  - `signoz_logs.distributed_logs_v2_resource`
  - `signoz_traces.distributed_signoz_index_v3`
  - `signoz_metrics.distributed_samples_v4`
- `signoz-otel-collector` logs showed repeated `context deadline exceeded` write failures and retries against ClickHouse.

## Root Cause

The primary instability was not a deviation from official SigNoz Docker topology. It was a platform-specific Kafka runtime problem:

- `kafka-platform` used a heavyweight healthcheck:
  - `env -u KAFKA_OPTS kafka-topics --bootstrap-server localhost:9092 --list`
- That command starts a JVM-based Kafka CLI.
- On this host, the command took about `17.70s`, but the configured timeout was only `5s`.
- Because the healthcheck ran every `10s`, overlapping checks accumulated and left behind large numbers of zombie Java processes.
- That pushed Kafka CPU and PID count up sharply and increased host-wide contention.
- Once the host was under pressure, the SigNoz collector started timing out while writing to ClickHouse, which amplified ClickHouse insert pressure and degraded API responsiveness.

This matches the measured data:

- Kafka was both unhealthy and heavily overloaded.
- ClickHouse was dominated by insert pressure, not dashboard read queries.
- Collector retries were visible in live logs.

## Safe Fix Applied

Changed file:

- `kafka-platform/docker-compose.yml`

Change:

- Replaced the JVM-based Kafka healthcheck with a lightweight TCP probe:
  - from: `env -u KAFKA_OPTS kafka-topics --bootstrap-server localhost:9092 --list >/dev/null 2>&1`
  - to: `nc -z localhost 9092`
- Increased healthcheck interval:
  - from `10s`
  - to `30s`

Why this is safe:

- It does not change Kafka broker configuration, listeners, topics, storage, or networking.
- It only changes how Docker decides whether the container is healthy.
- It follows the same lightweight healthcheck principle used in the official SigNoz Docker setup, where healthchecks are simple endpoint probes instead of heavyweight CLI clients.

## Runtime Evidence After Changes

After updating the healthcheck and recreating the Kafka container:

- `kafka-platform` health: `healthy`
- Kafka zombie Java process count: `0`
- Kafka runtime sample: about `169.02% CPU`, `550.4MiB` memory, `109` PIDs
- `signoz-clickhouse` runtime sample: about `95.55% CPU`
- `signoz-otel-collector` runtime sample: about `11.90% CPU`

Authenticated SigNoz API timings after recovery:

- `/api/v1/health`: about `0.255s`
- `/api/v1/dashboards`: about `0.777s`
- `/api/v1/dashboards/{generated}`: about `0.022s`

## Before vs After

| Signal | Before | After |
|---|---:|---:|
| Kafka health | unhealthy | healthy |
| Kafka healthcheck runtime | ~17.70s | lightweight TCP probe |
| Kafka CPU | ~336.90% | ~169.02% |
| Kafka memory | ~1.067GiB | ~550.4MiB |
| Kafka PIDs | 2976 | 109 |
| Kafka defunct Java processes | many | 0 |
| ClickHouse CPU | ~344.90% to ~517.40% | ~95.55% |
| OTel collector CPU | ~58.66% to ~75.90% | ~11.90% |
| SigNoz `/api/v1/health` | ~2.662s | ~0.255s |
| SigNoz `/api/v1/dashboards` | ~1.737s | ~0.777s |
| SigNoz dashboard detail | ~7.513s | ~0.022s |

## What Was Not Changed

These remain intentionally unchanged in this pass:

- Vault integration
- observer-stack Docker topology
- SigNoz bootstrap scripts
- alerts and channels
- existing dashboard definitions
- extra Kafka scrape pipeline in the observer-stack collector
- custom mounted frontend bundle

Those two local deviations from official SigNoz remain relevant for later dashboard UX debugging, but the measured runtime bottleneck in this pass was the Kafka healthcheck behavior.

## Stability Confirmation

Current status after the fix:

- runtime stabilized materially
- `kafka-platform` is healthy
- ClickHouse CPU reduced significantly
- SigNoz API latency improved substantially
- no working Vault/bootstrap/alert/channel behavior was changed

## Remaining Limitation

This report closes the runtime stabilization step. It does not by itself prove every dashboard route now renders cleanly in the browser. The next safe step is to resume browser-based dashboard validation from this healthier baseline and only patch remaining UI-specific issues if they still reproduce.
