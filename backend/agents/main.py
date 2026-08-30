"""FastAPI service exposing the Vigilux Sentinel fleet.

Endpoints:
  GET  /health        - liveness + fleet wiring summary
  POST /fleet/run     - executes the full four-agent monitoring pass and returns
                        the FleetReport
  GET  /fleet/status  - latest run, per-agent timings and registry entry

Each POST /fleet/run creates a fresh session keyed by a new run id and seeds
the run metadata (``temp:run_id``, ``temp:started_at``) through
``runner.run_async(state_delta=...)`` so every fleet agent can report where it
is in the run.
"""

from __future__ import annotations

import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from google.adk import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from .config import settings
from .models.schemas import (
    FLEET_AGENT_NAMES,
    FleetReport,
    FleetStatus,
    PerAgentTiming,
    RunLogEntry,
)
from .orchestrator import ORCHESTRATOR_NAME, build_orchestrator
from .tools import firestore_tool, observability

logger = logging.getLogger(__name__)

APP_NAME = settings.APP_NAME
USER_ID = settings.FLEET_USER_ID
TRIGGER_MESSAGE = (
    "Run the full Vigilux Sentinel fleet monitoring pass for all regions "
    "and return the FleetReport."
)

_orchestrator = build_orchestrator()
_session_service = InMemorySessionService()


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@asynccontextmanager
async def lifespan(app: FastAPI):
    observability.init_observability()
    logger.info("Vigilux Sentinel %s ready (agents: %s)", settings.APP_NAME, FLEET_AGENT_NAMES)
    yield


app = FastAPI(
    title="Vigilux Sentinel",
    description=(
        "Global outbreak-intelligence fleet: four google-adk agents "
        "(data-steward, risk-assessor, historian, curator) running under a "
        "SequentialAgent orchestrator."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict:
    """Liveness probe plus a summary of the fleet wiring."""
    return {
        "status": "ok",
        "service": APP_NAME,
        "orchestrator": ORCHESTRATOR_NAME,
        "fleet_agents": FLEET_AGENT_NAMES,
        "staleness_threshold_days": settings.SURVEY_STALENESS_THRESHOLD_DAYS,
        "memory_bank": (
            settings.MEMORY_BANK_AGENT_ENGINE_ID or "firestore-fallback"
        ),
        "cloud_trace_export_enabled": settings.OTEL_CLOUD_TRACE_ENABLED,
    }


@app.post("/fleet/run", response_model=FleetReport)
async def fleet_run() -> FleetReport:
    """Run the full monitoring pass and return the FleetReport."""
    run_id = uuid.uuid4().hex
    await _session_service.create_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=run_id
    )
    runner = Runner(
        app_name=APP_NAME, agent=_orchestrator, session_service=_session_service
    )
    events = []
    try:
        async for event in runner.run_async(
            user_id=USER_ID,
            session_id=run_id,
            state_delta={"temp:run_id": run_id, "temp:started_at": _iso_now()},
            new_message=types.Content(
                role="user",
                parts=[types.Part(text=TRIGGER_MESSAGE)],
            ),
        ):
            events.append(event)
    except Exception as exc:
        logger.exception("Fleet run %s failed", run_id)
        raise HTTPException(status_code=500, detail=f"Fleet run failed: {exc}") from exc

    final = next((e for e in reversed(events) if e.is_final_response()), None)
    if final is None or not (final.content and final.content.parts and final.content.parts[0].text):
        raise HTTPException(status_code=500, detail="Fleet run produced no final response.")
    try:
        return FleetReport.model_validate_json(final.content.parts[0].text)
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Curator returned an unparseable FleetReport: {exc}"
        ) from exc


@app.get("/fleet/status", response_model=FleetStatus)
def fleet_status() -> FleetStatus:
    """Latest run summary: report, per-agent timings, registry entry."""
    latest = firestore_tool.get_latest_fleet_run()
    if not latest:
        return FleetStatus(run_id=None, message="No fleet runs have completed yet.")

    try:
        report = FleetReport.model_validate(latest)
    except Exception:
        logger.warning("Latest fleet_runs doc for run %s is not a valid FleetReport", latest.get("run_id"))
        report = None

    observability_doc = firestore_tool.get_run_observability(latest.get("run_id", ""))
    timings = [
        PerAgentTiming(**record)
        for record in (observability_doc or {}).get("records", [])
    ]
    registry_entry = firestore_tool.get_latest_run_log_entry()
    return FleetStatus(
        run_id=latest.get("run_id"),
        latest_run=report,
        agent_timings=timings,
        registry_entry=RunLogEntry.model_validate(registry_entry) if registry_entry else None,
    )