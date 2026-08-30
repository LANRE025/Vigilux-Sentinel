"""historian: computes per-region trends against the Memory Bank.

For each assessment produced by the risk-assessor, the historian recalls the
most recent prior assessment for that region from the Memory Bank, produces a
``TrendNote`` (improving / worsening / unchanged / first_observation), then
stores this run's assessment so the next run can compare against it.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from google.adk.agents import BaseAgent
from google.adk.events import Event
from google.genai import types

from ..models.schemas import RiskLevel, TrendDirection, TrendNote
from ..tools import memory_bank_tool, observability

AGENT_NAME = "historian"

_LEVEL_PRIORITY = {
    RiskLevel.STABLE: 0,
    RiskLevel.WATCH: 1,
    RiskLevel.URGENT: 2,
}


def build_trend_note(
    previous: Optional[dict[str, Any]],
    current: dict[str, Any],
    runs_compared: int,
) -> dict[str, Any]:
    """Compare two assessments (dicts) and templated a TrendNote.

    ``previous`` is the prior assessment dict from the Memory Bank (or None for
    first observations). ``current`` is this run's assessment dict.
    """
    region_id = current["region_id"]
    current_level = current["risk_level"]
    previous_level = previous["risk_level"] if previous else None

    if previous_level is None:
        direction = TrendDirection.FIRST_OBSERVATION
        note = (
            f"First fleet assessment recorded for {region_id}; "
            f"baseline is {current_level}."
        )
    else:
        delta = _LEVEL_PRIORITY[current_level] - _LEVEL_PRIORITY[previous_level]
        if delta > 0:
            direction = TrendDirection.WORSENING
            note = (
                f"{region_id} moved from {previous_level} to {current_level} "
                f"across {runs_compared} fleet run(s)."
            )
        elif delta < 0:
            direction = TrendDirection.IMPROVING
            note = (
                f"{region_id} moved from {previous_level} to {current_level} "
                f"across {runs_compared} fleet run(s)."
            )
        else:
            direction = TrendDirection.UNCHANGED
            note = (
                f"{region_id} remains {current_level} across "
                f"{runs_compared} fleet run(s)."
            )

    return TrendNote(
        region_id=region_id,
        previous_risk_level=previous_level,
        current_risk_level=current_level,
        trend_direction=direction,
        runs_compared=runs_compared,
        note=note,
    ).model_dump(mode="json")


class HistorianAgent(BaseAgent):
    """Fleet agent that maintains cross-run region baselines via the Memory Bank."""

    name: str = AGENT_NAME
    tools: list[Any] = [
        memory_bank_tool.get_memory_bank,
        build_trend_note,
    ]
    instructions: str = (
        "For each assessment, recall the region's previous assessment from the "
        "Memory Bank, produce a TrendNote (first_observation/improving/worsening/"
        "unchanged), then store the new assessment back into the Memory Bank so "
        "the next fleet run can compare against it."
    )

    async def _run_async_impl(self, ctx):
        run_id = ctx.session.state.get("temp:run_id", "unknown")
        assessments: list[dict] = ctx.session.state.get("temp:assessments", [])
        memory = memory_bank_tool.get_memory_bank()

        with observability.agent_span(AGENT_NAME, run_id=run_id) as handle:
            notes: list[dict[str, Any]] = []
            for assessment in assessments:
                region_id = assessment["region_id"]
                previous = memory.recall_latest(region_id)
                runs_compared = memory.history_size(region_id) + 1
                notes.append(build_trend_note(previous, assessment, runs_compared))
                memory.store(region_id, assessment)
            ctx.session.state["temp:trend_notes"] = notes
            handle.set_region_count(len(assessments))
            yield Event(
                author=self.name,
                content=types.Content(
                    role="model",
                    parts=[types.Part(text=json.dumps(notes, indent=2) or "[]")],
                ),
            )