"""curator: merges assessments + trend notes into the final FleetReport.

Receives the run's ``SignalAssessment``s (from the risk-assessor) and
``TrendNote``s (from the historian), joins them on ``region_id``, sorts the
result (severity desc, then ``days_since_survey`` desc), counts/assembles a
``FleetReport``, persists it (FleetReport -> fleet_runs, per-agent telemetry ->
run_observability, run-log entry -> run_log), stores it under
``temp:fleet_report`` so the API can hand it straight to the caller, and
returns it as its response.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from google.adk.agents import BaseAgent
from google.adk.events import Event
from google.genai import types

from ..models.schemas import FLEET_AGENT_NAMES, FleetReport, ReportAssessment
from ..tools import firestore_tool, observability

AGENT_NAME = "curator"

_LEVEL_RANK = {"Stable": 0, "Watch": 1, "Urgent": 2}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sort_key(assessment: dict[str, Any]) -> tuple[int, int]:
    """Severity desc first, then days_since_survey desc (staler surveys first)."""
    return (-_LEVEL_RANK[assessment["risk_level"]], -assessment["days_since_survey"])


def build_fleet_report(
    assessments: list[dict[str, Any]],
    trend_notes: list[dict[str, Any]],
    run_id: str,
    started_at: str,
    *,
    missing_region_ids: list[str] | None = None,
) -> FleetReport:
    """Join assessments with their trend notes and assemble the FleetReport.

    Assessments are sorted Urgent -> Watch -> Stable, then by
    ``days_since_survey`` descending within the same risk level. A region whose
    TrendNote is missing (e.g. a defensive case) keeps ``trend: null`` instead
    of failing the run.
    """
    notes_by_region = {note["region_id"]: note for note in trend_notes}
    merged: list[dict[str, Any]] = []
    flagged = 0
    for assessment in assessments:
        if assessment["risk_level"] in ("Watch", "Urgent"):
            flagged += 1
        merged.append(
            {**assessment, "trend": notes_by_region.get(assessment["region_id"])}
        )
    merged.sort(key=_sort_key)

    return FleetReport(
        run_id=run_id,
        started_at=started_at,
        completed_at=_iso_now(),
        regions_evaluated=len(assessments),
        regions_flagged=flagged,
        assessments=[ReportAssessment(**a) for a in merged],
        missing_region_ids=missing_region_ids or [],
    )


class CuratorAgent(BaseAgent):
    """Fleet agent that finalizes and persists the FleetReport."""

    name: str = AGENT_NAME
    tools: list[Any] = [
        build_fleet_report,
        firestore_tool.write_fleet_report,
        firestore_tool.write_run_observability,
        firestore_tool.append_run_log_entry,
    ]
    instructions: str = (
        "Merge this run's assessments with their TrendNotes, sort by severity "
        "then staleness, count evaluations/flagging, persist the FleetReport "
        "(fleet_runs), attach the run's telemetry (run_observability), append "
        "the registry log entry (run_log), and return the report as JSON."
    )

    async def _run_async_impl(self, ctx):
        run_id = ctx.session.state.get("temp:run_id") or str(uuid.uuid4())
        started_at = ctx.session.state.get("temp:started_at", "")
        assessments: list[dict] = ctx.session.state.get("temp:assessments", [])
        trend_notes: list[dict] = ctx.session.state.get("temp:trend_notes", [])
        missing_region_ids: list[str] = ctx.session.state.get("temp:missing_region_ids", [])

        try:
            with observability.agent_span(AGENT_NAME, run_id=run_id) as handle:
                report = build_fleet_report(
                    assessments, trend_notes, run_id, started_at,
                    missing_region_ids=missing_region_ids,
                )
                handle.set_region_count(len(assessments))

            payload = report.model_dump(mode="json")
            firestore_tool.write_fleet_report(payload)
            firestore_tool.write_run_observability(
                run_id, observability.get_run_records(run_id)
            )
            firestore_tool.append_run_log_entry(
                run_id,
                started_at,
                report.completed_at,
                FLEET_AGENT_NAMES,
                "success",
            )
        except Exception as exc:
            firestore_tool.append_run_log_entry(
                run_id,
                started_at,
                _iso_now(),
                FLEET_AGENT_NAMES,
                "error",
                error=str(exc),
            )
            raise

        ctx.session.state["temp:fleet_report"] = payload
        yield Event(
            author=self.name,
            content=types.Content(
                role="model",
                parts=[types.Part(text=json.dumps(payload, indent=2))],
            ),
        )