"""Unit tests for the curator agent.

Covers final FleetReport assembly with mocked upstream agent outputs and mocked
Firestore writes:
  * SignalAssessments merged with their TrendNotes.
  * regions_evaluated / regions_flagged accounting.
  * Persistence calls (fleet_runs / run_observability / run_log).
"""

from __future__ import annotations

import json

from agents.curator.agent import CuratorAgent
from agents.models.schemas import FLEET_AGENT_NAMES
from agents.tools import firestore_tool, observability

from _util import FleetHarness, final_text


def assessment(region_id: str, risk: str) -> dict:
    return {
        "region_id": region_id,
        "country": "Testland",
        "risk_level": risk,
        "explanation": "test",
        "confidence": "Medium",
        "signals_used": ["admissions_pct_change"],
        "days_since_survey": 45,
        "assessed_at": "2026-08-01T00:00:00+00:00",
    }


def trend(region_id: str, direction: str, current: str) -> dict:
    return {
        "region_id": region_id,
        "previous_risk_level": "Stable" if direction != "first_observation" else None,
        "current_risk_level": current,
        "trend_direction": direction,
        "runs_compared": 2 if direction != "first_observation" else 1,
        "note": f"{direction} for {region_id}",
    }


async def test_curator_assembles_and_persists(monkeypatch) -> None:
    written = {}

    def record_write(name):
        def _write(payload):
            written[name] = payload
            return payload.get("run_id") if isinstance(payload, dict) else ""

        return _write

    monkeypatch.setattr(firestore_tool, "write_fleet_report", record_write("report"))
    monkeypatch.setattr(
        firestore_tool,
        "write_run_observability",
        lambda run_id, records: written.__setitem__("observability", (run_id, records)),
    )
    log_entries = []
    monkeypatch.setattr(
        firestore_tool,
        "append_run_log",
        lambda entry: log_entries.append(entry) or f"log-{entry['run_id']}",
    )
    timing_record = {
        "agent": "curator",
        "started_at": "2026-08-01T00:00:00+00:00",
        "ended_at": "2026-08-01T00:00:01+00:00",
        "duration_ms": 1.0,
        "regions_processed": 3,
        "error": None,
    }
    monkeypatch.setattr(
        observability, "get_run_records", lambda run_id: [timing_record]
    )

    assessments = [
        assessment("region-a-01", "Urgent"),
        assessment("region-b-01", "Watch"),
        assessment("region-c-01", "Stable"),
    ]
    notes = [
        trend("region-b-01", "worsening", "Watch"),
        trend("region-c-01", "first_observation", "Stable"),
    ]
    harness = FleetHarness(CuratorAgent())
    await harness.create_session()
    await harness.run(
        state_delta={
            "temp:run_id": "cur-test-run",
            "temp:started_at": "2026-08-01T00:00:00Z",
            "temp:assessments": assessments,
            "temp:trend_notes": notes,
        }
    )

    report = json.loads(final_text(harness.final) or "{}")
    assert report["run_id"] == "cur-test-run"
    assert report["started_at"] == "2026-08-01T00:00:00Z"
    assert report["completed_at"]
    assert report["regions_evaluated"] == 3
    assert report["regions_flagged"] == 2  # Urgent + Watch

    merged_by_id = {a["region_id"]: a for a in report["assessments"]}
    assert merged_by_id["region-b-01"]["trend"]["trend_direction"] == "worsening"
    assert merged_by_id["region-c-01"]["trend"]["trend_direction"] == "first_observation"
    assert merged_by_id["region-a-01"]["trend"] is None

    assert written["report"]["run_id"] == "cur-test-run"
    assert written["observability"][0] == "cur-test-run"
    assert written["observability"][1] == [timing_record]

    entry = log_entries[-1]
    assert entry["run_id"] == "cur-test-run"
    assert entry["outcome"] == "pass"
    assert entry["agents"] == FLEET_AGENT_NAMES
    assert entry["regions_evaluated"] == 3
    assert entry["regions_flagged"] == 2