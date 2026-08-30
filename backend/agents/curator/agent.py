"""curator: merges assessments + trends into the final FleetReport.

Receives the run's ``SignalAssessment``s and ``TrendNote``s, assembles the
``FleetReport`` payload, persists it (FleetReport -> fleet_runs, per-agent
telemetry -> run_observability, registry entry -> run_log), and returns the
report as its response so the API can hand it straight to the caller.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from google.adk.agents import BaseAgent
from google.adk.events import Event
from google.genai import types

from ..models.schemas import (
    FLEET_AGENT_NAMES,
    FleetReport,
    ReportAssessment,
    RunLogEntry,
)
from ..tools import firestore_tool, observability

AGENT_NAME = "curator"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_fleet_report(
    run_id: str,
    started_at: str,
    assessments: list[dict[str, Any]],
    notes_by_region: dict[str, dict[str, Any]],
) -> FleetReport:
    """Assemble the run's FleetReport, merging each assessment with its trend."""
    merged: list[ReportAssessment] = []
    flagged = 0
    for assessment in assessments:
        trend = notes_by_region.get(assessment["region_id"])
        if assessment["risk_level"] in ("Watch", "Urgent"):
            flagged += 1
        merged.append(ReportAssessment(**{**assessment, "trend": trend}))
    return FleetReport(
        run_id=run_id,
        started_at=started_at or _iso_now(),
        completed_at=_iso_now(),
        regions_evaluated=len(assessments),
        regions_flagged=flagged,
        assessments=merged,
    )


def build_run_log_entry(report: FleetReport) -> dict[str, Any]:
    return RunLogEntry(
        run_id=report.run_id,
        run_timestamp=report.completed_at,
        agents=FLEET_AGENT_NAMES,
        outcome="pass",
        regions_evaluated=report.regions_evaluated,
        regions_flagged=report.regions_flagged,
    ).model_dump(mode="json")


class CuratorAgent(BaseAgent):
    """Fleet agent that finalizes and persists the FleetReport."""

    name: str = AGENT_NAME
    tools: list[Any] = [
        build_fleet_report,
        firestore_tool.write_fleet_report,
        firestore_tool.write_run_observability,
        firestore_tool.append_run_log,
    ]
    instructions: str = (
        "Merge this run's SignalAssessments with their TrendNotes into a single "
        "FleetReport, persist it to Firestore (fleet_runs), attach the run's "
        "per-agent telemetry (run_observability) and append the registry log "
        "entry (run_log), then return the report as JSON."
    )

    async def _run_async_impl(self, ctx):
        run_id = ctx.session.state.get("temp:run_id", "unknown")
        started_at = ctx.session.state.get("temp:started_at", "")
        assessments: list[dict] = ctx.session.state.get("temp:assessments", [])
        notes: list[dict] = ctx.session.state.get("temp:trend_notes", [])
        notes_by_region = {note["region_id"]: note for note in notes}

        with observability.agent_span(AGENT_NAME, run_id=run_id) as handle:
            report = build_fleet_report(run_id, started_at, assessments, notes_by_region)
            handle.set_region_count(len(assessments))

        payload = report.model_dump(mode="json")
        firestore_tool.write_fleet_report(payload)
        firestore_tool.write_run_observability(
            run_id, observability.get_run_records(run_id)
        )
        firestore_tool.append_run_log(build_run_log_entry(report))

        ctx.session.state["temp:fleet_report"] = payload
        yield Event(
            author=self.name,
            content=types.Content(
                role="model",
                parts=[types.Part(text=json.dumps(payload, indent=2))],
            ),
        )