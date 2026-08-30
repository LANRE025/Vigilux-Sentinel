"""Unit tests for the historian agent.

Covers cross-run comparison via a mocked Memory Bank:
  * First observations and worsened/improved/unchanged trends.
  * The Memory Bank is written back for each region so the next run can
    compare against it.
"""

from __future__ import annotations

import json

from agents.historian.agent import HistorianAgent, build_trend_note
from agents.models.schemas import RiskLevel as RL
from agents.historian import agent as ha
from agents.tools import memory_bank_tool

from _util import FleetHarness, final_text


class FakeMemoryBank:
    def __init__(self, priors: dict[str, dict | None] | None = None):
        self._priors = dict(priors or {})
        self.recalled: list[str] = []
        self.stored: list[tuple[str, dict]] = []

    def recall_latest(self, region_id: str) -> dict | None:
        self.recalled.append(region_id)
        return self._priors.get(region_id)

    def store(self, region_id: str, assessment: dict) -> None:
        self.stored.append((region_id, assessment))

    def history_size(self, region_id: str) -> int:
        return 1 if self._priors.get(region_id) else 0


def assessment(region_id: str, risk: str) -> dict:
    return {
        "region_id": region_id,
        "country": "Testland",
        "risk_level": risk,
        "explanation": "test",
        "confidence": "Medium",
        "signals_used": ["admissions_pct_change"],
        "days_since_survey": 40,
        "assessed_at": "2026-08-01T00:00:00+00:00",
    }


async def test_trends_and_memory_writeback(monkeypatch) -> None:
    """region-a worsens (Stable->Watch), region-b is a first observation."""
    memory = FakeMemoryBank(
        priors={"region-a-01": assessment("region-a-01", "Stable")}
    )
    monkeypatch.setattr(memory_bank_tool, "get_memory_bank", lambda: memory)

    assessments = [
        assessment("region-a-01", "Watch"),
        assessment("region-b-01", "Stable"),
    ]
    harness = FleetHarness(HistorianAgent())
    await harness.create_session()
    await harness.run(
        state_delta={
            "temp:run_id": "hist-test-run",
            "temp:assessments": assessments,
        }
    )

    notes = json.loads(final_text(harness.final) or "[]")
    by_region = {n["region_id"]: n for n in notes}

    assert by_region["region-a-01"]["trend_direction"] == "worsening"
    assert by_region["region-a-01"]["previous_risk_level"] == "Stable"
    assert by_region["region-a-01"]["current_risk_level"] == "Watch"
    assert by_region["region-a-01"]["runs_compared"] == 2

    assert by_region["region-b-01"]["trend_direction"] == "first_observation"
    assert by_region["region-b-01"]["previous_risk_level"] is None
    assert by_region["region-b-01"]["runs_compared"] == 1

    stored_regions = {region for region, _ in memory.stored}
    assert stored_regions == {"region-a-01", "region-b-01"}
    assert memory.recalled == ["region-a-01", "region-b-01"]


def test_build_trend_note_directions() -> None:
    assert build_trend_note(
        assessment("r", "Stable"), assessment("r", "Watch"), 2
    )["trend_direction"] == "worsening"

    assert build_trend_note(
        assessment("r", "Urgent"), assessment("r", "Watch"), 5
    )["trend_direction"] == "improving"

    assert build_trend_note(
        assessment("r", "Watch"), assessment("r", "Watch"), 3
    )["trend_direction"] == "unchanged"

    first = build_trend_note(None, assessment("r", "Stable"), 1)
    assert first["trend_direction"] == "first_observation"
    assert first["previous_risk_level"] is None