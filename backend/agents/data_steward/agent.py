"""data_steward: retrieves all region snapshots from Firestore.

Pure retrieval, no LLM call. The output (a JSON list of region snapshots) is
yielded as the agent's response and handed to the risk-assessor via
``temp:region_snapshots`` session state.
"""

from __future__ import annotations

import json
from typing import Any

from google.adk.agents import BaseAgent
from google.adk.events import Event
from google.genai import types

from ..models.schemas import RegionSnapshot
from ..tools import firestore_tool, observability

AGENT_NAME = "data_steward"


class DataStewardAgent(BaseAgent):
    """Fleet agent responsible for reading the current field snapshot data."""

    name: str = AGENT_NAME
    tools: list[Any] = [firestore_tool.read_region_snapshots]
    instructions: str = (
        "Read all region snapshots from the region_snapshots Firestore "
        "collection and hand them to the rest of the fleet as structured "
        "data. No reasoning or LLM call is required: pure retrieval."
    )

    async def _run_async_impl(self, ctx):
        run_id = ctx.session.state.get("temp:run_id", "unknown")
        with observability.agent_span(AGENT_NAME, run_id=run_id) as handle:
            documents = firestore_tool.read_region_snapshots()
            snapshots = [
                RegionSnapshot(**document).model_dump(mode="json")
                for document in documents
            ]
            ctx.session.state["temp:region_snapshots"] = snapshots
            handle.set_region_count(len(snapshots))
            yield Event(
                author=self.name,
                content=types.Content(
                    role="model",
                    parts=[types.Part(text=json.dumps(snapshots, indent=2) or "[]")],
                ),
            )