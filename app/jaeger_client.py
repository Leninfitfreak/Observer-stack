from typing import Any
from urllib.parse import urlencode

from utils import request_with_retry


class JaegerClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def query_slow_traces(self, service: str, limit: int = 5, min_duration_ms: int = 500) -> dict[str, Any]:
        params = {
            "service": service,
            "limit": "30",
            "lookback": "1h",
            "minDuration": f"{min_duration_ms}ms",
        }
        resp = request_with_retry("GET", f"{self.base_url}/api/traces?{urlencode(params)}")
        payload = resp.json()
        traces = payload.get("data", [])

        slow_traces: list[dict[str, Any]] = []
        error_span_count = 0
        for trace in traces:
            spans = trace.get("spans", [])
            if not spans:
                continue
            max_span = max(spans, key=lambda s: s.get("duration", 0))
            duration_ms = round(float(max_span.get("duration", 0)) / 1000.0, 2)
            if duration_ms < min_duration_ms:
                continue

            span_errors = 0
            for span in spans:
                tags = span.get("tags", [])
                for tag in tags:
                    if tag.get("key") == "error" and str(tag.get("value")).lower() == "true":
                        span_errors += 1
                        break
            error_span_count += span_errors

            slow_traces.append(
                {
                    "trace_id": trace.get("traceID", "unknown"),
                    "max_span_operation": max_span.get("operationName", "unknown"),
                    "max_span_duration_ms": duration_ms,
                    "span_count": len(spans),
                    "error_span_count": span_errors,
                }
            )

        slow_traces.sort(key=lambda x: x["max_span_duration_ms"], reverse=True)
        top_traces = slow_traces[:limit]

        critical_path = None
        if top_traces:
            t0 = top_traces[0]
            critical_path = f'{t0["max_span_operation"]} ({t0["max_span_duration_ms"]}ms)'

        summary = "No slow traces (>500ms) found."
        if top_traces:
            summary = f"Top {len(top_traces)} slow traces found; longest critical path candidate: {critical_path}."

        return {
            "slow_traces": top_traces,
            "error_span_count": error_span_count,
            "longest_critical_path": critical_path,
            "summary": summary,
        }
