"""Unit tests for the curator agent.

Covers final FleetReport assembly with mocked upstream outputs and mocked
Firestore writes:
  * Join + accounting (regions_evaluated / regions_flagged).
  * Exact sort order (severity desc, then days_since_survey desc).
  * Defensive handling: a missing TrendNote becomes trend: null, no failure.
  * Persistence (fleet_runs doc id == run_id, run_log "success" entry,
    "error" entry + re-raise when aggregation fails).
  * temp:fleet_report populated for the API (verified via a probe sub-agent,
    mirroring how the orchestrator hands off across sub-agents).
"""

from __future__ import annotations

import json

import pytest
from google.adk.agents import BaseAgent, SequentialAgent
from google.adk.events import Event
from google.genai import types

from agents.curator.agent import CuratorAgent, build_fleet_report
from agents.models.schemas import FLEET_AGENT_NAMES, FleetReport
from agents.tools import firestore_tool

from _util import FleetHarness, final_text


def assessment(region_id: str, risk: str, days_since_survey: int = 45) -> dict:
    return {
        "region_id": region_id,
        "country": "Testland",
        "risk_level": risk,
        "explanation": "test",
        "confidence": "Medium",
        "signals_used": ["admissions_pct_change"],
        "days_since_survey": days_since_survey,
        "assessed_at": "2026-08-01T00:00:00+00:00",
    }


def trend(region_id: str, direction: str, current: str) -> dict:
    return {
        "region_id": region_id,
        "previous_risk_level": "Stable" if direction != "first_observation" else None,
        "current_risk_level": current,
        "trend_direction": direction,
        "runs_compared": 2 if direction != "first_observation" else 0,
        "note": f"{direction} for {region_id}",
    }


def patch_firestore(
    monkeypatch,
    written_reports: list,
    written_obs: list,
    log_calls: list,
) -> None:
    monkeypatch.setattr(
        firestore_tool, "write_fleet_report", lambda payload: written_reports.append(payload)
    )
    monkeypatch.setattr(
        firestore_tool,
        "write_run_observability",
        lambda run_id, records: written_obs.append((run_id, records)),
    )
    monkeypatch.setattr(
        firestore_tool,
        "append_run_log_entry",
        lambda run_id, started_at, completed_at, agents_ran, status, error=None: (
            log_calls.append((run_id, started_at, completed_at, agents_ran, status, error))
        ),
    )


# ---------------------------------------------------------------------------
# Pure aggregation
# ---------------------------------------------------------------------------
def test_build_fleet_report_basic_aggregation() -> None:
    assessments = [
        assessment("u1", "Urgent"),
        assessment("w1", "Watch"),
        assessment("s1", "Stable"),
    ]
    notes = [
        trend("u1", "worsening", "Urgent"),
        trend("w1", "unchanged", "Watch"),
        trend("s1", "first_observation", "Stable"),
    ]
    report = build_fleet_report(assessments, notes, "run-1", "2026-08-01T00:00:00Z")

    assert report.run_id == "run-1"
    assert report.started_at == "2026-08-01T00:00:00Z"
    assert report.completed_at
    assert report.regions_evaluated == 3
    assert report.regions_flagged == 2  # Urgent + Watch only
    assert len(report.assessments) == 3
    assert {a.trend.trend_direction for a in report.assessments} == {
        "worsening",
        "unchanged",
        "first_observation",
    }


def test_build_fleet_report_sort_order() -> None:
    """Urgent > Watch > Stable, and days_since_survey desc within each level."""
    assessments = [
        assessment("u-old", "Urgent", 60),
        assessment("u-new", "Urgent", 30),
        assessment("w-mid", "Watch", 40),
        assessment("w-new", "Watch", 10),
        assessment("s-any", "Stable", 90),
    ]
    report = build_fleet_report(assessments, [], "run-1", "")
    order = [a.region_id for a in report.assessments]
    assert order == ["u-old", "u-new", "w-mid", "w-new", "s-any"]


def test_build_fleet_report_missing_trend_is_null() -> None:
    assessments = [assessment("a1", "Watch"), assessment("b1", "Stable")]
    notes = [trend("b1", "first_observation", "Stable")]  # a1 -> no TrendNote
    report = build_fleet_report(assessments, notes, "run-1", "")

    by_id = {a.region_id: a for a in report.assessments}
    assert by_id["a1"].trend is None
    assert by_id["b1"].trend is not None
    assert report.regions_evaluated == 2
    assert report.regions_flagged == 1


def test_build_fleet_report_stable_regions_not_flagged() -> None:
    report = build_fleet_report(
        [
            assessment("u1", "Urgent"),
            assessment("w1", "Watch"),
            assessment("s1", "Stable"),
            assessment("s2", "Stable"),
        ],
        [],
        "run-1",
        "",
    )
    assert report.regions_evaluated == 4
    assert report.regions_flagged == 2


# ---------------------------------------------------------------------------
# Full agent runs (mocked Firestore)
# ---------------------------------------------------------------------------
async def test_curator_full_run_persists_and_logs(monkeypatch) -> None:
    written_reports: list[dict] = []
    written_obs: list[tuple] = []
    log_calls: list[tuple] = []
    patch_firestore(monkeypatch, written_reports, written_obs, log_calls)

    assessments = [
        assessment("scan-03", "Stable", 70),
        assessment("scan-02", "Urgent", 12),
        assessment("scan-01", "Watch", 33),
        assessment("scan-04", "Urgent", 9),
    ]
    notes = [trend(r, "worsening", a["risk_level"]) for r, a in zip(
        ["scan-01", "scan-02", "scan-03", "scan-04"], assessments
    )]

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
    assert report["regions_evaluated"] == 4
    assert report["regions_flagged"] == 3  # scan-03 Stable excluded
    assert [a["region_id"] for a in report["assessments"]] == [
        "scan-02",  # Urgent, staler
        "scan-04",  # Urgent, fresher
        "scan-01",  # Watch
        "scan-03",  # Stable
    ]

    # write_fleet_report: document ID == run_id
    assert written_reports[-1]["run_id"] == "cur-test-run"
    assert written_obs[-1][0] == "cur-test-run"

    # append_run_log_entry: success on a normal run
    (
        log_run_id,
        log_started,
        log_completed,
        log_agents,
        log_status,
        log_error,
    ) = log_calls[-1]
    assert log_run_id == "cur-test-run"
    assert log_started == "2026-08-01T00:00:00Z"
    assert log_completed == report["completed_at"]
    assert log_agents == FLEET_AGENT_NAMES
    assert log_status == "success"
    assert log_error is None


async def test_curator_missing_started_at_passes_through_empty(monkeypatch) -> None:
    """temp:started_at absent -> Curator passes the raw empty value through.

    The key is omitted entirely so ``.get("temp:started_at", "")`` falls back
    to its default, exactly as a caller who forgot to record the run start
    would trigger it. No timestamp is fabricated and the run succeeds.
    """
    written_reports: list[dict] = []
    written_obs: list[tuple] = []
    log_calls: list[tuple] = []
    patch_firestore(monkeypatch, written_reports, written_obs, log_calls)

    harness = FleetHarness(CuratorAgent())
    await harness.create_session()
    await harness.run(
        state_delta={
            "temp:run_id": "cur-no-start-run",
            "temp:assessments": [
                assessment("u1", "Urgent"),
                assessment("s1", "Stable"),
            ],
            "temp:trend_notes": [
                trend("u1", "worsening", "Urgent"),
                trend("s1", "first_observation", "Stable"),
            ],
        }
    )

    report = json.loads(final_text(harness.final) or "{}")
    assert report["run_id"] == "cur-no-start-run"
    assert report["started_at"] == ""  # raw pass-through, no guessed timestamp
    assert report["completed_at"]
    assert report["regions_evaluated"] == 2
    assert report["regions_flagged"] == 1

    # Normal success path: report persisted + success log, not the error branch.
    assert written_reports[-1]["run_id"] == "cur-no-start-run"
    assert log_calls[-1][4] == "success"


async def test_curator_aggregation_error_logs_error_and_reraises(monkeypatch) -> None:
    written_reports: list[dict] = []
    written_obs: list[tuple] = []
    log_calls: list[tuple] = []
    patch_firestore(monkeypatch, written_reports, written_obs, log_calls)

    bad = {**assessment("x1", "Stable"), "risk_level": "Mega"}  # unrankable
    harness = FleetHarness(CuratorAgent())
    await harness.create_session()
    with pytest.raises(KeyError):
        await harness.run(
            state_delta={
                "temp:run_id": "cur-fail-run",
                "temp:assessments": [bad],
                "temp:trend_notes": [],
            }
        )

    (log_run_id, _started, _completed, log_agents, log_status, error) = log_calls[-1]
    assert log_run_id == "cur-fail-run"
    assert log_agents == FLEET_AGENT_NAMES
    assert log_status == "error"
    assert "Mega" in error


class _StateProbe(BaseAgent):
    """Trivial sub-agent that reports temp:fleet_report, like POST /fleet/run."""

    name: str = "probe"
    instructions: str = "Report the fleet report from session state."
    tools: list = []

    async def _run_async_impl(self, ctx):
        report = ctx.session.state.get("temp:fleet_report")
        yield Event(
            author=self.name,
            content=types.Content(
                role="model", parts=[types.Part(text=json.dumps(report))]
            ),
        )


async def test_curator_populates_fleet_report_in_session_state(monkeypatch) -> None:
    written_reports: list[dict] = []
    written_obs: list[tuple] = []
    log_calls: list[tuple] = []
    patch_firestore(monkeypatch, written_reports, written_obs, log_calls)

    fleet = SequentialAgent(
        name="curator_fleet", sub_agents=[CuratorAgent(), _StateProbe()]
    )
    harness = FleetHarness(fleet)
    await harness.create_session()
    await harness.run(
        state_delta={
            "temp:run_id": "cur-state-run",
            "temp:started_at": "2026-08-01T00:00:00Z",
            "temp:assessments": [
                assessment("s1", "Stable"),
                assessment("u1", "Urgent"),
            ],
            "temp:trend_notes": [
                trend("s1", "first_observation", "Stable"),
                trend("u1", "worsening", "Urgent"),
            ],
        }
    )

    state_report = json.loads(final_text(harness.final) or "{}")
    assert state_report
    parsed = FleetReport(**state_report)  # must validate against the schema
    assert parsed.run_id == "cur-state-run"
    assert parsed.started_at == "2026-08-01T00:00:00Z"
    assert parsed.regions_evaluated == 2
    assert parsed.regions_flagged == 1
    assert [a.region_id for a in parsed.assessments] == ["u1", "s1"]
    assert all(a.trend is not None for a in parsed.assessments)


# --- missing_region_ids pass-through ----------------------------------------
def test_build_fleet_report_missing_region_ids() -> None:
    report = build_fleet_report(
        [assessment("s1", "Stable")],
        [trend("s1", "first_observation", "Stable")],
        "run-missing",
        "2026-08-01T00:00:00Z",
        missing_region_ids=["ghost-01", "ghost-02"],
    )
    assert report.missing_region_ids == ["ghost-01", "ghost-02"]


def test_build_fleet_report_no_missing_region_ids() -> None:
    report = build_fleet_report(
        [assessment("s1", "Stable")],
        [trend("s1", "first_observation", "Stable")],
        "run-nomiss",
        "2026-08-01T00:00:00Z",
    )
    assert report.missing_region_ids == []


async def test_curator_agent_passes_through_missing_region_ids(monkeypatch):
    """The curator reads temp:missing_region_ids and forwards it into FleetReport."""
    written_reports: list[dict] = []
    written_obs: list[tuple] = []
    log_calls: list[tuple] = []
    patch_firestore(monkeypatch, written_reports, written_obs, log_calls)

    fleet = SequentialAgent(
        name="curator_fleet", sub_agents=[CuratorAgent(), _StateProbe()]
    )
    harness = FleetHarness(fleet)
    await harness.create_session()
    await harness.run(
        state_delta={
            "temp:run_id": "cur-missing-run",
            "temp:started_at": "2026-08-01T00:00:00Z",
            "temp:assessments": [assessment("s1", "Stable")],
            "temp:trend_notes": [trend("s1", "first_observation", "Stable")],
            "temp:missing_region_ids": ["ghost-01", "ghost-02"],
        }
    )

    state_report = json.loads(final_text(harness.final) or "{}")
    parsed = FleetReport(**state_report)
    assert parsed.missing_region_ids == ["ghost-01", "ghost-02"]
    assert parsed.regions_evaluated == 1