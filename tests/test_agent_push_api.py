from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from ai_observer.api.app import create_app


def _seed_incident(client: TestClient, cluster_id: str) -> None:
    payload = {
        "cluster_id": cluster_id,
        "incidents": [
            {
                "incident_id": f"INC-{cluster_id}",
                "service_name": "product-service",
                "anomaly_score": 0.21,
                "confidence_score": 0.72,
                "classification": "Performance Degradation",
                "root_cause": "latency",
                "mitigation": {"actions": ["restart"]},
                "risk_forecast": 0.33,
            }
        ],
    }
    response = client.post("/api/agent/push", json=payload, headers={"X-Agent-Token": "test-token"})
    assert response.status_code == 200


def test_agent_push_auth_and_cluster_filter(monkeypatch, tmp_path) -> None:
    db_file = tmp_path / "agent.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{db_file}")
    monkeypatch.setenv("AGENT_TOKEN", "test-token")
    monkeypatch.setenv("PROMETHEUS_URL", "http://example-prom")
    monkeypatch.setenv("LOKI_URL", "http://example-loki")
    monkeypatch.setenv("JAEGER_URL", "http://example-jaeger")

    app = create_app()
    client = TestClient(app)

    unauthorized = client.post("/api/agent/push", json={"cluster_id": "x", "incidents": []})
    assert unauthorized.status_code == 401

    _seed_incident(client, "cluster-a")
    _seed_incident(client, "cluster-b")

    params = {
        "start_date": date.today().isoformat(),
        "end_date": date.today().isoformat(),
        "cluster": "cluster-a",
    }
    response = client.get("/api/incidents", params=params)
    assert response.status_code == 200

    body = response.json()
    assert body["data"]
    assert all(item["cluster_id"] == "cluster-a" for item in body["data"])

    default_response = client.get(
        "/api/incidents",
        params={"start_date": date.today().isoformat(), "end_date": date.today().isoformat()},
    )
    assert default_response.status_code == 200
    assert default_response.json()["total_count"] >= 2