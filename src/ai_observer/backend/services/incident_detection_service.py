from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, desc
from sqlalchemy.orm import Session

from ai_observer.backend.models.incident import Incident, TelemetrySample
from ai_observer.backend.services.incidents_service import IncidentsService
from ai_observer.domain.models import AlertSignal
from ai_observer.incident_analysis.database import get_session

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DetectionDecision:
    score: float
    severity: str
    root: str
    triggered: bool


class IncidentDetectionEngine:
    def __init__(self, app):
        self._app = app
        self._task: asyncio.Task | None = None
        self._running = False

    @property
    def settings(self):
        return self._app.state.container.settings.detection

    async def start(self) -> None:
        if not self.settings.enabled or self._task is not None:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="incident-detection-engine")
        logger.info(
            "Incident detection engine started interval=%ss threshold=%s mode=%s",
            self.settings.interval_seconds,
            self.settings.anomaly_threshold,
            self.settings.service_discovery_mode,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Incident detection engine stopped")

    async def _loop(self) -> None:
        while self._running:
            try:
                await asyncio.to_thread(self.scan_once)
            except Exception:
                logger.exception("Incident detection scan failed")
            await asyncio.sleep(self.settings.interval_seconds)

    @staticmethod
    def _as_float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def evaluate_sample(self, sample: TelemetrySample, session: Session) -> DetectionDecision:
        lookback_start = sample.captured_at - timedelta(hours=1)
        history = (
            session.query(TelemetrySample)
            .filter(
                and_(
                    TelemetrySample.cluster_id == sample.cluster_id,
                    TelemetrySample.namespace == sample.namespace,
                    TelemetrySample.service_name == sample.service_name,
                    TelemetrySample.captured_at >= lookback_start,
                    TelemetrySample.id != sample.id,
                )
            )
            .order_by(desc(TelemetrySample.captured_at))
            .limit(240)
            .all()
        )
        cpu = self._as_float(sample.cpu_usage)
        mem = self._as_float(sample.memory_usage)
        rps = self._as_float(sample.request_rate)
        err = self._as_float(sample.error_rate)
        restarts = self._as_float(sample.pod_restarts)

        cpu_threshold_score = min(1.0, cpu / 0.8) if cpu > 0 else 0.0
        error_threshold_score = min(1.0, err / 0.05) if err > 0 else 0.0
        restart_threshold_score = min(1.0, restarts / 1.0) if restarts > 0 else 0.0

        def mean_std(values: list[float]) -> tuple[float, float]:
            if not values:
                return 0.0, 0.0
            m = sum(values) / len(values)
            if len(values) <= 1:
                return m, 0.0
            var = sum((x - m) ** 2 for x in values) / len(values)
            return m, var ** 0.5

        def zscore(current: float, mean: float, std: float) -> float:
            denom = max(std, abs(mean) * 0.1, 1e-6)
            return (current - mean) / denom

        cpu_hist = [self._as_float(x.cpu_usage) for x in history]
        mem_hist = [self._as_float(x.memory_usage) for x in history]
        rps_hist = [self._as_float(x.request_rate) for x in history]
        err_hist = [self._as_float(x.error_rate) for x in history]

        cpu_m, cpu_s = mean_std(cpu_hist)
        mem_m, mem_s = mean_std(mem_hist)
        rps_m, rps_s = mean_std(rps_hist)
        err_m, err_s = mean_std(err_hist)

        cpu_baseline = min(1.0, abs(zscore(cpu, cpu_m, cpu_s)) / 3.0) if cpu_hist else 0.0
        mem_baseline = min(1.0, abs(zscore(mem, mem_m, mem_s)) / 3.0) if mem_hist else 0.0
        rps_baseline = min(1.0, abs(zscore(rps, rps_m, rps_s)) / 3.0) if rps_hist else 0.0
        err_baseline = min(1.0, abs(zscore(err, err_m, err_s)) / 3.0) if err_hist else 0.0

        score = min(
            1.0,
            (0.2 * cpu_threshold_score)
            + (0.28 * error_threshold_score)
            + (0.08 * restart_threshold_score)
            + (0.16 * cpu_baseline)
            + (0.14 * mem_baseline)
            + (0.08 * rps_baseline)
            + (0.06 * err_baseline),
        )
        root = "metrics_within_expected_range"
        if error_threshold_score >= 1.0:
            root = "error_rate_threshold_breached"
        elif cpu_threshold_score >= 1.0:
            root = "cpu_usage_threshold_breached"
        elif score >= self.settings.anomaly_threshold:
            root = "baseline_deviation_zscore_high"
        immediate_trigger = error_threshold_score >= 1.0 or cpu_threshold_score >= 1.0 or restart_threshold_score >= 1.0
        triggered = (score >= self.settings.anomaly_threshold) or immediate_trigger
        if immediate_trigger and score < self.settings.anomaly_threshold:
            score = max(score, self.settings.anomaly_threshold)
        severity = "warning" if score < 0.85 else "critical"
        return DetectionDecision(score=score, severity=severity, root=root, triggered=triggered)

    def _incident_recently_created(self, session: Session, sample: TelemetrySample) -> bool:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max(30, self.settings.interval_seconds * 2))
        exists = (
            session.query(Incident)
            .filter(
                and_(
                    Incident.cluster_id == sample.cluster_id,
                    Incident.affected_services == sample.service_name,
                    Incident.created_at >= cutoff,
                )
            )
            .first()
        )
        return exists is not None

    def _create_incident_from_sample(self, session: Session, sample: TelemetrySample, score: float, severity: str) -> str:
        alert = AlertSignal(
            alertname="TelemetryAnomaly",
            namespace=sample.namespace,
            service=sample.service_name,
            cluster_id=sample.cluster_id,
            severity=severity,
            status="firing",
        )
        payload = sample.raw_payload if isinstance(sample.raw_payload, dict) else {}
        metrics = {
            "cpu_usage": self._as_float(sample.cpu_usage),
            "memory_usage": self._as_float(sample.memory_usage),
            "request_rate": self._as_float(sample.request_rate),
            "error_rate": self._as_float(sample.error_rate),
            "pod_restarts": self._as_float(sample.pod_restarts),
            "latency": self._as_float(sample.latency),
            "anomaly_score": score,
        }
        payload = {**payload, "metrics": {**(payload.get("metrics") or {}), **metrics}, "namespace": sample.namespace, "service_name": sample.service_name}
        service = IncidentsService(session)
        incident_id = service.persist_from_telemetry_sample(
            alert=alert,
            metrics=metrics,
            raw_payload=payload,
            reasoner=self._app.state.container.reasoning_service,
            window_minutes=self._app.state.container.settings.telemetry.default_window_minutes,
        )
        logger.info(
            "Incident created by detector incident_id=%s cluster=%s namespace=%s service=%s anomaly_score=%.3f",
            incident_id,
            sample.cluster_id,
            sample.namespace,
            sample.service_name,
            score,
        )
        return incident_id

    def scan_once(self) -> int:
        session = get_session()
        created = 0
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=max(60, self.settings.interval_seconds * 3))
            rows = (
                session.query(TelemetrySample)
                .filter(TelemetrySample.captured_at >= cutoff)
                .order_by(desc(TelemetrySample.captured_at))
                .limit(300)
                .all()
            )
            latest: dict[tuple[str, str, str], TelemetrySample] = {}
            for row in rows:
                key = (row.cluster_id, row.namespace, row.service_name)
                if key not in latest:
                    latest[key] = row
            for sample in latest.values():
                decision = self.evaluate_sample(sample, session)
                if not decision.triggered:
                    continue
                if self._incident_recently_created(session, sample):
                    continue
                self._create_incident_from_sample(session, sample, decision.score, decision.severity)
                created += 1
            if created:
                logger.info("Incident detection scan complete created=%s", created)
            return created
        finally:
            session.close()
