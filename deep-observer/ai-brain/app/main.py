from __future__ import annotations

import logging
import time

from .config import get_settings
from .db import (
    create_predictive_incident,
    fetch_historical_matches,
    fetch_known_services,
    fetch_pending_incidents,
    fetch_reasoned_incidents_without_runbook,
    postgres_connection,
    store_runbook,
    predictive_incident_exists,
    store_reasoning,
    store_reasoning_validation,
)
from .llm.client import build_llm_client
from .reasoner import fallback_reasoning, generate_reasoning
from .runbook_generator import generate_runbook
from .telemetry import TelemetryReader
from .validation_engine import validate_reasoning


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> None:
    settings = get_settings()
    llm = build_llm_client(settings)
    telemetry = TelemetryReader(settings)

    try:
        while True:
            with postgres_connection(settings) as conn:
                for prediction in telemetry.detect_predictive_anomalies():
                    try:
                        if predictive_incident_exists(
                            conn,
                            prediction.get("cluster", ""),
                            prediction.get("namespace", ""),
                            prediction.get("service", ""),
                        ):
                            continue
                        predictive_id = create_predictive_incident(conn, settings, prediction)
                        logging.info(
                            "created predictive incident %s for service=%s score=%.2f",
                            predictive_id,
                            prediction.get("service", ""),
                            prediction.get("anomaly_score", 0.0),
                        )
                    except Exception as exc:  # noqa: BLE001
                        logging.exception("predictive incident creation failed: %s", exc)

                incidents = fetch_pending_incidents(conn, settings)
                if not incidents:
                    logging.info("no pending incidents")
                for incident in incidents:
                    try:
                        context = telemetry.fetch_context(incident)
                        historical_matches = fetch_historical_matches(conn, incident)
                        reasoning = generate_reasoning(llm, incident, context, historical_matches)
                        validation = validate_reasoning(incident, context, reasoning, fetch_known_services(conn))
                        store_reasoning_validation(conn, validation)
                        if validation.validation_result == "unsupported":
                            regenerated = fallback_reasoning(incident, context, historical_matches)
                            regenerated["confidence_score"] = min(
                                regenerated.get("confidence_score", 0.6),
                                validation.confidence_score,
                            )
                            unsupported = ", ".join(validation.unsupported_statements[:3])
                            regenerated["impact_assessment"] = (
                                f"{regenerated.get('impact_assessment', '')} "
                                f"Validation warning: unsupported claims were removed ({unsupported})."
                            ).strip()
                            reasoning = regenerated
                        store_reasoning(conn, incident, reasoning)
                        store_runbook(conn, generate_runbook(incident, reasoning, historical_matches))
                        logging.info("stored reasoning for incident %s", incident["incident_id"])
                    except Exception as exc:  # noqa: BLE001
                        logging.exception("reasoning failed for incident %s: %s", incident["incident_id"], exc)

                for row in fetch_reasoned_incidents_without_runbook(conn, limit=5):
                    try:
                        synthetic_incident = {
                            "incident_type": row.get("incident_type", "observed"),
                            "namespace": row.get("namespace", ""),
                            "service": row.get("service", ""),
                            "detector_signals": row.get("detector_signals", []),
                        }
                        synthetic_reasoning = {
                            "root_cause_signal": row.get("root_cause_signal", "unknown"),
                            "recommended_actions": row.get("recommended_actions", []),
                            "correlated_signals": row.get("detector_signals", []),
                        }
                        store_runbook(conn, generate_runbook(synthetic_incident, synthetic_reasoning, []))
                    except Exception as exc:  # noqa: BLE001
                        logging.exception("runbook backfill failed: %s", exc)
            time.sleep(settings.poll_interval_seconds)
    finally:
        telemetry.close()


if __name__ == "__main__":
    main()
