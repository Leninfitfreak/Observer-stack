# Kafka Platform Architecture

## Repository
- Repo: `C:\Projects\Services\kafka-platform`
- Files:
  - `docker-compose.yml`
  - `create-topics.sh`

## Deployment Model
- Kafka runs outside Kubernetes via Docker Compose.
- Single broker, KRaft mode (no ZooKeeper).
- Container: `kafka-platform`
- Port exposed: `9092`
- Persistent volume: `kafka_data`

## Key Kafka Configuration
- `KAFKA_PROCESS_ROLES=broker,controller`
- `KAFKA_CONTROLLER_LISTENER_NAMES=CONTROLLER`
- `KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://host.minikube.internal:9092`
- `KAFKA_AUTO_CREATE_TOPICS_ENABLE=false`

This advertised listener is critical so pods in Minikube can reach Kafka at:
- `host.minikube.internal:9092`

## Topic Provisioning
`create-topics.sh` creates:
- `product-events` (3 partitions, rf=1)
- `order-events` (3 partitions, rf=1)
- `order-created` (3 partitions, rf=1)

Current microservice code also uses `product-orders` topic for product -> order workflow, so ensure that topic exists in the broker if required by current runtime.

## How Kubernetes Services Connect
Helm values for product/order services set:
- `KAFKA_BOOTSTRAP_SERVERS=host.minikube.internal:9092`
- `SPRING_KAFKA_BOOTSTRAP_SERVERS=host.minikube.internal:9092`

`hostAliases` are used in Helm values to map `host.minikube.internal` for pod DNS resolution.

## Operational Commands
```bash
# Start platform
docker compose up -d

# Create topics
./create-topics.sh

# Verify
docker compose ps
```

