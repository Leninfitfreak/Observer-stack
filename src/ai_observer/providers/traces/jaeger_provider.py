from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from ai_observer.infra.http_client import HttpClient


class JaegerTracesProvider:
    def __init__(self, base_url: str, http: HttpClient):
        self.base_url = base_url.rstrip("/")
        self.http = http

    def collect(self, service: str, lookback_minutes: int, limit: int = 5) -> dict[str, Any]:
        params = urlencode(
            {
                "service": service,
                "lookback": f"{lookback_minutes}m",
                "limit": str(limit),
                "minDuration": "500ms",
            }
        )
        resp = self.http.request("GET", f"{self.base_url}/api/traces?{params}")
        traces = resp.json().get("data", [])[:limit]
        slow = []
        for trace in traces:
            trace_id = trace.get("traceID", "unknown")
            spans = trace.get("spans", [])
            max_duration_ms = max([(span.get("duration", 0) or 0) / 1000 for span in spans], default=0)
            slow.append({"trace_id": trace_id, "max_span_duration_ms": round(max_duration_ms, 2)})

        return {
            "slow_traces": slow,
            "error_span_count": 0,
            "longest_critical_path": None,
            "summary": f"Collected {len(slow)} traces from Jaeger.",
        }
