from __future__ import annotations

import contextlib
import logging
import signal
import uuid
from datetime import datetime, timezone
import time

from .config import get_settings
from .db import (
    create_predictive_incident,
    fetch_historical_matches,
    fetch_known_services,
    fetch_pending_incidents,
    fetch_reasoning_requests,
    fetch_reasoned_incidents_without_runbook,
    postgres_connection,
    store_runbook,
    predictive_incident_exists,
    store_reasoning,
    store_reasoning_validation,
    claim_reasoning_request,
    fail_stale_reasoning_requests,
    update_reasoning_request_status,
    create_reasoning_run,
    update_reasoning_run,
)
from .llm.client import build_llm_client
from .reasoner import fallback_reasoning, generate_reasoning
from .runbook_generator import generate_runbook
from .telemetry import TelemetryReader
from .validation_engine import validate_reasoning


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


class ReasoningTimeoutError(TimeoutError):
    pass


def reasoning_timeout_seconds(settings) -> int:
    return max(60, int(settings.llm_timeout_seconds))


def stale_reasoning_timeout_seconds(settings) -> int:
    return reasoning_timeout_seconds(settings) + max(15, int(settings.poll_interval_seconds))


def backend_failure_message(exc: Exception) -> str:
    detail = str(exc).strip() or exc.__class__.__name__
    lowered = detail.lower()
    if any(token in lowered for token in ("topology", "telemetry", "clickhouse", "trace", "metric", "log")):
        return f"Reasoning failed due to backend error (topology/telemetry unavailable): {detail}"
    return f"Reasoning failed due to backend error: {detail}"


@contextlib.contextmanager
def reasoning_deadline(timeout_seconds: int):
    if timeout_seconds <= 0 or not hasattr(signal, "setitimer"):
        yield
        return

    def _handle_timeout(_signum, _frame):
        raise ReasoningTimeoutError(f"Reasoning failed due to backend timeout after {timeout_seconds}s")

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
    signal.signal(signal.SIGALRM, _handle_timeout)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, previous_timer[0], previous_timer[1])


def main() -> None:
    settings = get_settings()
    llm = build_llm_client(settings)
    telemetry = TelemetryReader(settings)
    timeout_seconds = reasoning_timeout_seconds(settings)
    stale_timeout_seconds = stale_reasoning_timeout_seconds(settings)
    auto_reasoning = settings.reasoning_mode.lower() == "auto" or settings.reasoning_auto_trigger
    if auto_reasoning:
        logging.info("reasoning mode: auto")
    else:
        logging.info("reasoning mode: manual")

    try:
        while True:
            with postgres_connection(settings) as conn:
                expired = fail_stale_reasoning_requests(
                    conn,
                    stale_timeout_seconds,
                    f"Reasoning failed due to backend timeout after {timeout_seconds}s",
                )
                if expired:
                    logging.warning("marked stale reasoning requests as failed: %s", ", ".join(expired))

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

                incidents = fetch_pending_incidents(conn, settings) if auto_reasoning else fetch_reasoning_requests(conn, settings)
                if not incidents:
                    logging.info("no pending incidents" if auto_reasoning else "no reasoning requests")
                for incident in incidents:
                    run_id = None
                    fallback_used = False
                    model_failure = ""
                    try:
                        with reasoning_deadline(timeout_seconds):
                            if not auto_reasoning and not claim_reasoning_request(conn, incident["incident_id"]):
                                continue
                            trigger_type = incident.get("trigger_type") or "manual"
                            logging.info(
                                "reasoning_event=request_claimed incident_id=%s trigger_type=%s mode=%s",
                                incident["incident_id"],
                                trigger_type,
                                "auto" if auto_reasoning else "manual",
                            )
                            run_id = str(uuid.uuid4())
                            provider = settings.llm_provider
                            model = settings.openai_model if provider.startswith("openai") else settings.ollama_model
                            create_reasoning_run(
                                conn,
                                {
                                    "reasoning_run_id": run_id,
                                    "incident_id": incident["incident_id"],
                                    "status": "running",
                                    "provider": provider,
                                    "model": model,
                                    "trigger_type": trigger_type,
                                    "started_at": datetime.now(timezone.utc),
                                    "completed_at": None,
                                },
                            )
                            logging.info(
                                "reasoning_event=worker_pickup incident_id=%s run_id=%s provider=%s model=%s",
                                incident["incident_id"],
                                run_id,
                                provider,
                                model,
                            )
                            context = telemetry.fetch_context(incident)
                            historical_matches = fetch_historical_matches(conn, incident)
                            try:
                                logging.info(
                                    "reasoning_event=model_invocation_dispatch incident_id=%s run_id=%s provider=%s model=%s",
                                    incident["incident_id"],
                                    run_id,
                                    provider,
                                    model,
                                )
                                reasoning = generate_reasoning(llm, incident, context, historical_matches)
                            except Exception as exc:  # noqa: BLE001
                                fallback_used = True
                                model_failure = str(exc).strip() or exc.__class__.__name__
                                logging.warning(
                                    "reasoning_event=fallback_selected incident_id=%s run_id=%s provider=%s model=%s error=%s",
                                    incident["incident_id"],
                                    run_id,
                                    provider,
                                    model,
                                    model_failure,
                                )
                                reasoning = fallback_reasoning(incident, context, historical_matches)
                                reasoning["impact_assessment"] = (
                                    f"{reasoning.get('impact_assessment', '')} "
                                    "LLM generation was unavailable, so this summary is based on deterministic telemetry evidence."
                                ).strip()
                                reasoning["execution_mode"] = "fallback"
                                reasoning["model_failure_summary"] = model_failure
                            else:
                                reasoning["execution_mode"] = "model"
                                reasoning["model_failure_summary"] = ""
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
                                regenerated["execution_mode"] = "fallback"
                                regenerated["model_failure_summary"] = (
                                    f"Validation removed unsupported model output ({unsupported})."
                                )
                                fallback_used = True
                                if not model_failure:
                                    model_failure = regenerated["model_failure_summary"]
                                reasoning = regenerated
                            store_reasoning(conn, incident, reasoning)
                            store_runbook(conn, generate_runbook(incident, reasoning, historical_matches))
                            update_reasoning_run(
                                conn,
                                run_id,
                                {
                                    "status": "completed_with_fallback" if fallback_used else "completed",
                                    "error_message": model_failure if fallback_used else "",
                                    "summary": reasoning.get("root_cause", ""),
                                    "root_cause_service": reasoning.get("root_cause_service", ""),
                                    "root_cause_signal": reasoning.get("root_cause_signal", ""),
                                    "root_cause_confidence": reasoning.get("confidence_score", 0.0),
                                    "suggested_actions": reasoning.get("recommended_actions", []),
                                    "propagation_path": reasoning.get("propagation_path", []),
                                    "evidence_snapshot": {
                                        "signals": incident.get("detector_signals", []),
                                        "telemetry_summary": incident.get("timeline_summary", []),
                                        "execution_mode": reasoning.get("execution_mode", "model"),
                                        "model_failure_summary": reasoning.get("model_failure_summary", ""),
                                    },
                                    "confidence_explanation": reasoning.get("confidence_explanation", {}),
                                    "correlation_summary": reasoning.get("correlation_summary", ""),
                                    "completed_at": datetime.now(timezone.utc),
                                },
                            )
                            logging.info(
                                "reasoning_event=persisted incident_id=%s run_id=%s status=%s root_cause_service=%s root_cause_signal=%s confidence=%s execution_mode=%s",
                                incident["incident_id"],
                                run_id,
                                "completed_with_fallback" if fallback_used else "completed",
                                reasoning.get("root_cause_service", ""),
                                reasoning.get("root_cause_signal", ""),
                                reasoning.get("confidence_score", 0.0),
                                reasoning.get("execution_mode", "model"),
                            )
                            if not auto_reasoning:
                                update_reasoning_request_status(
                                    conn,
                                    incident["incident_id"],
                                    "completed_with_fallback" if fallback_used else "completed",
                                    model_failure if fallback_used else "",
                                )
                    except ReasoningTimeoutError as exc:
                        error_message = str(exc)
                        logging.exception("reasoning_event=timeout incident_id=%s run_id=%s error=%s", incident["incident_id"], run_id, error_message)
                        if run_id:
                            try:
                                update_reasoning_run(
                                    conn,
                                    run_id,
                                    {
                                        "status": "failed",
                                        "error_message": error_message,
                                        "completed_at": datetime.now(timezone.utc),
                                    },
                                )
                            except Exception:  # noqa: BLE001
                                pass
                        if not auto_reasoning:
                            update_reasoning_request_status(conn, incident["incident_id"], "failed", error_message)
                    except Exception as exc:  # noqa: BLE001
                        error_message = backend_failure_message(exc)
                        logging.exception("reasoning_event=failed incident_id=%s run_id=%s error=%s", incident["incident_id"], run_id, error_message)
                        try:
                            if run_id:
                                update_reasoning_run(
                                    conn,
                                    run_id,
                                    {
                                        "status": "failed",
                                        "error_message": error_message,
                                        "completed_at": datetime.now(timezone.utc),
                                    },
                                )
                        except Exception:  # noqa: BLE001
                            pass
                        if not auto_reasoning:
                            update_reasoning_request_status(conn, incident["incident_id"], "failed", error_message)

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
