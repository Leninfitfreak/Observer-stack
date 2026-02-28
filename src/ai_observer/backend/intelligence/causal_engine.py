from __future__ import annotations

from typing import Any


class CausalEngine:
    @staticmethod
    def build_causal_chain(origin_service: str, impacted_services: list[str], propagation_path: list[str]) -> list[str]:
        chain: list[str] = []
        if origin_service and origin_service != "unknown":
            chain.append(f"Origin service inferred from topology: {origin_service}.")
        if propagation_path:
            chain.append(f"Propagation path: {' -> '.join(propagation_path)}.")
        if impacted_services:
            chain.append(f"Impacted services: {', '.join(impacted_services[:8])}.")
        return chain

    @staticmethod
    def enrich_analysis(analysis: dict[str, Any], origin_service: str, causal_chain: list[str]) -> dict[str, Any]:
        out = dict(analysis or {})
        out["origin_service"] = origin_service or "unknown"
        existing_chain = out.get("causal_chain", [])
        if not isinstance(existing_chain, list):
            existing_chain = []
        out["causal_chain"] = [*existing_chain, *causal_chain]
        return out
