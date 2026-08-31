"""data_steward: raw region_snapshots -> canonical stale-region signals.

Pure retrieval + deterministic normalization, no LLM call. The agent:

  1. Reads every document from the region_snapshots Firestore collection via
     the firestore_tool layer.
  2. Normalizes each into the canonical ``RegionSignal`` shape the rest of the
     fleet contracts on - independent of whatever the raw storage field names
     happen to be.
  3. Recomputes staleness in days against the ACTUAL current date at run time
     (never a fixed reference date) and derives ``funding_pct_of_avg`` from the
     absolute-dollar funding fields (funding_usd / regional_avg_funding_usd).
  4. Keeps only (region, disease) documents at/above the evaluation threshold
     (``DATA_STEWARD_STALENESS_THRESHOLD_DAYS``, INCLUSIVE at the boundary) and
     hands the canonical signals to the fleet via ``temp:region_snapshots``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable

from google.adk.agents import BaseAgent
from google.adk.events import Event
from google.genai import types

from ..config import settings
from ..models.schemas import RegionSignal
from ..tools import firestore_tool, observability

AGENT_NAME = "data_steward"


def staleness_days(snapshot: dict, now: datetime) -> int:
    """Whole days between ``now`` and the snapshot's survey time (>= 0).

    Staleness is ALWAYS recomputed at run time from ``last_survey_at``; the
    stored ``days_since_survey`` value (seed-time) is deliberately not trusted,
    because seed time != run time.
    """
    try:
        survey_at = datetime.fromisoformat(snapshot["last_survey_at"])
    except (KeyError, ValueError) as exc:
        raise ValueError(
            f"cannot parse last_survey_at for {snapshot.get('region_id', '?')}: "
            f"{snapshot.get('last_survey_at')!r}"
        ) from exc
    if survey_at.tzinfo is None:
        survey_at = survey_at.replace(tzinfo=timezone.utc)
    return max((now - survey_at).days, 0)


def funding_pct_of_avg(snapshot: dict) -> float:
    """funding_usd (absolute dollars) as a percentage of regional average."""
    avg = snapshot.get("regional_avg_funding_usd") or 0.0
    if avg <= 0:
        return 0.0
    return round((snapshot.get("funding_usd") or 0.0) / avg * 100.0, 1)


def build_region_signals(
    documents: Iterable[dict[str, Any]],
    *,
    threshold_days: int | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Canonical signals for documents at/above the evaluation threshold.

    Pure and fixture-driven: Firestore and clock access are injected, so unit
    tests exercise this directly without touching the network.

    Threshold semantics: INCLUSIVE - a document whose staleness EXACTLY equals
    ``threshold_days`` IS evaluated. The default threshold comes from settings
    (``DATA_STEWARD_STALENESS_THRESHOLD_DAYS``); pass ``threshold_days`` to
    override.
    """
    threshold = (
        settings.DATA_STEWARD_STALENESS_THRESHOLD_DAYS
        if threshold_days is None
        else threshold_days
    )
    current = now or datetime.now(timezone.utc)
    signals: list[dict[str, Any]] = []
    for doc in documents:
        days_stale = staleness_days(doc, current)
        if days_stale < threshold:
            continue
        signals.append(
            RegionSignal(
                region=doc["region_id"],
                country=doc["country"],
                disease=doc.get("disease"),
                days_stale=days_stale,
                admissions_pct_change=float(doc["admissions_pct_change"]),
                funding_pct_of_avg=funding_pct_of_avg(doc),
                evaluated_at=current.isoformat(),
            ).model_dump(mode="json")
        )
    return signals


def collect_region_signals() -> list[dict[str, Any]]:
    """Read the live region_snapshots collection and return its signals."""
    return build_region_signals(firestore_tool.read_region_snapshots())


class DataStewardAgent(BaseAgent):
    """Fleet agent that reads field snapshots and emits canonical signals."""

    name: str = AGENT_NAME
    tools: list[Any] = [firestore_tool.read_region_snapshots]
    instructions: str = (
        "Read all region snapshots from the region_snapshots Firestore "
        "collection and normalize each into a canonical RegionSignal: region, "
        "country, disease, days_stale, admissions_pct_change, "
        "funding_pct_of_avg, evaluated_at. Recompute staleness against the "
        "current date and keep only regions at or above the evaluation "
        "threshold. No reasoning or LLM call - pure retrieval and transform."
    )

    async def _run_async_impl(self, ctx):
        run_id = ctx.session.state.get("temp:run_id", "unknown")
        requested_ids: list[str] | None = ctx.session.state.get("temp:region_ids")
        with observability.agent_span(AGENT_NAME, run_id=run_id) as handle:
            all_docs = firestore_tool.read_region_snapshots()
            docs = all_docs
            missing_ids: list[str] = []
            if requested_ids:
                doc_id_set = {d.get("region_id") for d in all_docs}
                wanted = set(requested_ids)
                docs = [d for d in all_docs if d.get("region_id") in wanted]
                missing_ids = [rid for rid in requested_ids if rid not in doc_id_set]
            signals = build_region_signals(docs)
            ctx.session.state["temp:region_snapshots"] = signals
            if missing_ids:
                ctx.session.state["temp:missing_region_ids"] = missing_ids
            handle.set_region_count(len(signals))
            yield Event(
                author=self.name,
                content=types.Content(
                    role="model",
                    parts=[types.Part(text=json.dumps(signals, indent=2) or "[]")],
                ),
            )