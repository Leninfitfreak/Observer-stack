import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

from utils import request_with_retry


class LokiClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        known = os.getenv("KNOWN_ERROR_SIGNATURES", "")
        self.known_signatures = {s.strip() for s in known.split(",") if s.strip()}
        self.default_apps = [s.strip() for s in os.getenv("ALL_SERVICES", "product-service,order-service").split(",") if s.strip()]

    def _build_query(self, namespace: str, service: str) -> str:
        svc = (service or "").strip()
        if svc.lower() in {"", "*", "all"}:
            apps = self.default_apps
        else:
            apps = [s.strip() for s in svc.split(",") if s.strip()]

        if apps:
            escaped = "|".join(re.escape(a) for a in apps)
            selector = (
                f'{{namespace="{namespace}",pod=~".*({escaped}).*",container!="istio-proxy"}}'
            )
        else:
            selector = f'{{namespace="{namespace}",container!="istio-proxy"}}'

        return (
            f'{selector} |= "ERROR"'
            ' != "loki-gateway"'
            ' != "component=querier"'
            ' != "component=frontend"'
            ' != "query_range"'
        )

    def _normalize_signature(self, line: str) -> str:
        s = line.lower()
        s = re.sub(r"0x[0-9a-f]+", "<hex>", s)
        s = re.sub(r"\b\d+\b", "<num>", s)
        s = re.sub(r"[a-f0-9]{16,}", "<id>", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s[:180]

    def query_errors(self, namespace: str, service: str, minutes: int = 5, limit: int = 20) -> dict[str, Any]:
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=minutes)
        query = self._build_query(namespace=namespace, service=service)
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
        signature_counts: dict[str, int] = {}
        for stream in streams:
            for _, line in stream.get("values", []):
                cleaned = line.strip()
                if not cleaned:
                    continue
                clipped = cleaned[:320]
                lines.append(clipped)
                sig = self._normalize_signature(clipped)
                signature_counts[sig] = signature_counts.get(sig, 0) + 1
                if len(lines) >= limit:
                    break
            if len(lines) >= limit:
                break

        top_signatures = sorted(signature_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        top_signature_rows = [{"signature": sig, "count": cnt} for sig, cnt in top_signatures]
        new_signatures = [s for s, _ in top_signatures if s not in self.known_signatures]

        summary = "No ERROR logs found in last 5 minutes."
        if lines:
            summary = f"Found {len(lines)} ERROR lines and {len(top_signatures)} clustered signatures."
            if new_signatures:
                summary += f" New signature candidates: {len(new_signatures)}."

        return {
            "query": query,
            "count": len(lines),
            "lines": lines,
            "top_signatures": top_signature_rows,
            "new_signatures": new_signatures,
            "summary": summary,
        }
