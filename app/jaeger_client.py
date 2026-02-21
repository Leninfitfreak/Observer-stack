from typing import Any
from urllib.parse import urlencode

from utils import request_with_retry


class JaegerClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def query_slow_traces(self, service: str, limit: int = 5, min_duration_ms: int = 500) -> dict[str, Any]:
        params = {
            "service": service,
            "limit": "20",
            "lookback": "1h",
            "minDuration": f"{min_duration_ms}ms",
        }
        resp = request_with_retry("GET", f"{self.base_url}/api/traces?{urlencode(params)}")
        payload = resp.json()
        traces = payload.get("data", [])

        summaries: list[dict[str, Any]] = []
        for trace in traces:
            spans = trace.get("spans", [])
            if not spans:
                continue
            max_span = max(spans, key=lambda s: s.get("duration", 0))
            duration_ms = round(float(max_span.get("duration", 0)) / 1000.0, 2)
            if duration_ms < min_duration_ms:
                continue
            summaries.append(
                {
                    "trace_id": trace.get("traceID", "unknown"),
                    "max_span_operation": max_span.get("operationName", "unknown"),
                    "max_span_duration_ms": duration_ms,
                    "span_count": len(spans),
                }
            )

        summaries.sort(key=lambda x: x["max_span_duration_ms"], reverse=True)
        top_summaries = summaries[:limit]

        summary_text = "No slow traces (>500ms) found."
        if top_summaries:
            compact = [
                f'{s["trace_id"]}:{s["max_span_operation"]}({s["max_span_duration_ms"]}ms)'
                for s in top_summaries
            ]
            summary_text = f"Top slow traces: {'; '.join(compact)}"

        return {"slow_traces": top_summaries, "summary": summary_text}
