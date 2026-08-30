"""Observability for the Vigilux Sentinel fleet.

Every agent wraps its execution in an ``agent_span``. Each span does two things:

1. Opens a real OpenTelemetry span (exported to Cloud Trace when
   ``OTEL_CLOUD_TRACE_ENABLED`` is true and the Cloud Trace exporter is
   available, e.g. on Cloud Run).

2. Records a JSON timing record keyed by ``run_id`` so the curator can persist
   per-agent timings to Firestore (``run_observability``) and the
   ``/fleet/status`` endpoint can report them.

Records are kept in a small in-process buffer (bounded, oldest runs dropped).
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Optional

from opentelemetry import trace

from ..config import settings

logger = logging.getLogger(__name__)

_RUN_RECORDS: dict[str, list[dict]] = {}
_MAX_RUNS_KEPT = 50
_LOCK = threading.Lock()


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_observability() -> bool:
    """Set up the global OpenTelemetry tracer provider.

    Returns True when exporting to Cloud Trace is enabled/configured.
    """
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(
        resource=Resource.create({SERVICE_NAME: settings.APP_NAME})
    )
    exported = False
    if settings.OTEL_CLOUD_TRACE_ENABLED:
        try:
            from opentelemetry.exporter.gcp.trace import CloudTraceSpanExporter

            provider.add_span_processor(
                BatchSpanProcessor(
                    CloudTraceSpanExporter(project_id=settings.GOOGLE_CLOUD_PROJECT or None)
                )
            )
            exported = True
        except Exception as exc:  # missing dep or credentials: keep tracing in-memory
            logger.warning("Cloud Trace exporter unavailable: %s", exc)
    trace.set_tracer_provider(provider)
    return exported


def _append_record(run_id: str, record: dict) -> None:
    with _LOCK:
        buffer = _RUN_RECORDS.setdefault(run_id, [])
        buffer.append(record)
        while len(_RUN_RECORDS) > _MAX_RUNS_KEPT:
            _RUN_RECORDS.pop(next(iter(_RUN_RECORDS)))


def get_run_records(run_id: str) -> list[dict]:
    """Per-agent timing records captured so far for a run."""
    return list(_RUN_RECORDS.get(run_id, []))


@contextmanager
def agent_span(
    agent_name: str,
    run_id: str = "",
    regions_processed: int = 0,
):
    """Context manager wrapping one agent's execution in an OTel span.

    Exposes ``span.set_region_count(n)`` and ``span.set_error(exc)`` helpers
    to the wrapped agent code. A JSON record is appended to the run buffer on
    exit; exceptions are recorded and re-raised.
    """
    tracer = trace.get_tracer(settings.APP_NAME)
    started = time.time()
    started_at = _iso_now()
    region_count = regions_processed
    error: Optional[str] = None

    with tracer.start_as_current_span(
        f"agent.{agent_name}",
        attributes={"run_id": run_id or "", "regions_processed": region_count},
    ) as otel_span:
        def set_region_count(count: int) -> None:
            nonlocal region_count
            region_count = count
            otel_span.set_attribute("regions_processed", count)

        def set_error(exc: Exception) -> None:
            nonlocal error
            error = str(exc)
            otel_span.record_exception(exc)
            otel_span.set_attribute("error", str(exc))

        try:
            yield SimpleNamespace(set_region_count=set_region_count, set_error=set_error)
        except Exception as exc:
            set_error(exc)
            raise
        finally:
            otel_span.set_attribute("agent.duration_ms", round((time.time() - started) * 1000.0, 3))
            _append_record(
                run_id,
                {
                    "agent": agent_name,
                    "started_at": started_at,
                    "ended_at": _iso_now(),
                    "duration_ms": round((time.time() - started) * 1000.0, 3),
                    "regions_processed": region_count,
                    "error": error,
                },
            )