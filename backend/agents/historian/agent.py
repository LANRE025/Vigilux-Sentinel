"""historian: computes per-region trends against Firestore assessment history.

For each assessment produced by the risk-assessor, the historian reads that
region's history from the ``assessment_history`` collection, produces a
``TrendNote`` (improving / worsening / unchanged / first_observation), then
appends this run's assessment so the next run can compare against it. Entries
are trimmed to the most recent ``HISTORY_MAX_ENTRIES`` per region.

The comparison baseline for a region is read once, on that region's first
encounter in the run; nothing written earlier in the same run is ever treated
as "previous", so two assessments for the same region_id in one run both
compare against the same pre-run document.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from google.adk.agents import BaseAgent
from google.adk.events import Event
from google.genai import types

from ..models.schemas import RiskLevel, TrendDirection, TrendNote
from ..tools import firestore_tool, observability

AGENT_NAME = "historian"

HISTORY_MAX_ENTRIES = 5

_LEVEL_RANK = {
    RiskLevel.STABLE.value: 0,
    RiskLevel.WATCH.value: 1,
    RiskLevel.URGENT.value: 2,
}


def _rank(risk_level: str) -> int:
    """Severity rank of a risk-level string (Stable < Watch < Urgent)."""
    return _LEVEL_RANK[RiskLevel(risk_level).value]


def compute_trend(
    current: dict[str, Any],
    previous_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a TrendNote for ``current`` against the last prior entry.

    ``previous_entries`` is the region's history BEFORE this run's assessment,
    ordered oldest to newest; only the last entry is compared against.
    ``runs_compared`` counts how many prior entries existed (capped at
    ``HISTORY_MAX_ENTRIES``), so 0 means a first observation.
    """
    region_id = current["region_id"]
    current_level = current["risk_level"]
    previous = previous_entries[-1] if previous_entries else None
    previous_level = previous["risk_level"] if previous else None
    runs_compared = min(len(previous_entries), HISTORY_MAX_ENTRIES)

    if previous_level is None:
        direction = TrendDirection.FIRST_OBSERVATION
        note = f"First assessment on record for {region_id}."
    else:
        delta = _rank(current_level) - _rank(previous_level)
        if delta > 0:
            direction = TrendDirection.WORSENING
            note = (
                f"Risk has escalated from {previous_level} to {current_level} "
                f"since the last assessment."
            )
        elif delta < 0:
            direction = TrendDirection.IMPROVING
            note = (
                f"Risk has eased from {previous_level} to {current_level} "
                f"since the last assessment."
            )
        else:
            direction = TrendDirection.UNCHANGED
            note = f"Risk remains {current_level} since the last assessment."

    return TrendNote(
        region_id=region_id,
        previous_risk_level=previous_level,
        current_risk_level=current_level,
        trend_direction=direction,
        runs_compared=runs_compared,
        note=note,
    ).model_dump(mode="json")


def _recorded_entry(assessment: dict[str, Any]) -> dict[str, Any]:
    """Stamp a SignalAssessment with its recorded_at timestamp."""
    return {**assessment, "recorded_at": datetime.now(timezone.utc).isoformat()}


def _history_entries(doc: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Extract the entries array from an assessment-history document."""
    if not doc:
        return []
    entries = doc.get("entries")
    if not isinstance(entries, list):
        return []
    return [e for e in entries if isinstance(e, dict)]


def _append_to_history(
    entries: list[dict[str, Any]],
    new_entry: dict[str, Any],
    cap: int = HISTORY_MAX_ENTRIES,
) -> list[dict[str, Any]]:
    """Append ``new_entry`` keeping only the last ``cap`` entries (oldest dropped)."""
    return (list(entries) + [new_entry])[-cap:]


class HistorianAgent(BaseAgent):
    """Fleet agent that maintains cross-run region baselines in assessment_history."""

    name: str = AGENT_NAME
    tools: list[Any] = [
        compute_trend,
        firestore_tool.read_assessment_history,
        firestore_tool.write_assessment_history,
    ]
    instructions: str = (
        "For each assessment, read the region's history from assessment_history, "
        "produce a TrendNote (first_observation/improving/worsening/unchanged), "
        "then append this run's assessment (trimmed to the last 5 entries) back "
        "to the same document so the next fleet run can compare against it."
    )

    async def _run_async_impl(self, ctx):
        run_id = ctx.session.state.get("temp:run_id", "unknown")
        assessments: list[dict] = ctx.session.state.get("temp:assessments", [])
        # Per-region state captured ONCE per run: prior[:region] holds the
        # PRE-RUN baseline (read lazily on first encounter, reused for every
        # assessment of that region), persist[:region] is what gets written
        # back (baseline + this run's appends). This guarantees read-before-
        # write: a region is never compared against an entry written earlier
        # in the same run.
        prior: dict[str, list[dict[str, Any]]] = {}
        persist: dict[str, list[dict[str, Any]]] = {}

        with observability.agent_span(AGENT_NAME, run_id=run_id) as handle:
            notes: list[dict[str, Any]] = []
            for assessment in assessments:
                region_id = assessment["region_id"]
                if region_id not in prior:
                    doc = firestore_tool.read_assessment_history(region_id)
                    prior[region_id] = _history_entries(doc)
                    persist[region_id] = list(prior[region_id])

                notes.append(compute_trend(assessment, prior[region_id]))

                persist[region_id] = _append_to_history(
                    persist[region_id], _recorded_entry(assessment)
                )
                firestore_tool.write_assessment_history(
                    region_id, {"region_id": region_id, "entries": persist[region_id]}
                )

            ctx.session.state["temp:trend_notes"] = notes
            handle.set_region_count(len(assessments))
            yield Event(
                author=self.name,
                content=types.Content(
                    role="model",
                    parts=[types.Part(text=json.dumps(notes, indent=2) or "[]")],
                ),
            )