from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

from utils import request_with_retry


class LokiClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def query_errors(self, namespace: str, service: str, minutes: int = 5, limit: int = 20) -> dict[str, Any]:
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=minutes)
        query = f'{{namespace="{namespace}"}} |= "ERROR" |= "{service}"'
        params = {
            "query": query,
            "start": str(int(start.timestamp() * 1e9)),
            "end": str(int(end.timestamp() * 1e9)),
            "limit": str(limit),
            "direction": "BACKWARD",
        }
        resp = request_with_retry(
            "GET",
            f"{self.base_url}/loki/api/v1/query_range?{urlencode(params)}",
        )
        payload = resp.json()
        streams = payload.get("data", {}).get("result", [])

        lines: list[str] = []
        for stream in streams:
            for _, line in stream.get("values", []):
                cleaned = line.strip()
                if cleaned:
                    lines.append(cleaned)
                if len(lines) >= limit:
                    break
            if len(lines) >= limit:
                break

        summary = "No ERROR logs found in last 5 minutes."
        if lines:
            summary = f"Found {len(lines)} ERROR lines. Sample: " + " | ".join(lines[:5])

        return {
            "query": query,
            "count": len(lines),
            "lines": lines,
            "summary": summary,
        }
