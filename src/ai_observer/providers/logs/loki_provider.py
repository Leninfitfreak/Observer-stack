from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from ai_observer.infra.http_client import HttpClient


class LokiLogsProvider:
    def __init__(self, base_url: str, http: HttpClient):
        self.base_url = base_url.rstrip("/")
        self.http = http

    def collect(self, namespace: str, service: str, minutes: int, limit: int = 20) -> dict[str, Any]:
        query = f'{{namespace="{namespace}",pod=~".*{service}.*"}} |= "ERROR"'
        params = urlencode({"query": query, "limit": str(limit), "direction": "backward"})
        resp = self.http.request("GET", f"{self.base_url}/loki/api/v1/query_range?{params}")
        result = resp.json().get("data", {}).get("result", [])

        lines: list[str] = []
        for stream in result:
            for entry in stream.get("values", []):
                if len(entry) > 1:
                    lines.append(entry[1])
                if len(lines) >= limit:
                    break
            if len(lines) >= limit:
                break

        return {
            "count": len(lines),
            "lines": lines,
            "summary": f"Collected {len(lines)} error lines from Loki in last {minutes}m.",
            "top_signatures": [],
            "new_signatures": [],
        }
