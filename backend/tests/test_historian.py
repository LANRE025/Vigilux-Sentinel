"""Unit tests for the historian agent.

Covers cross-run comparison via a mocked ``assessment_history`` Firestore
store (no live project):
  * Trend logic: first_observation / unchanged / worsening / improving.
  * runs_compared reflects the number of prior entries (0 on first observation).
  * Histories are trimmed to the last 5 entries (oldest dropped).
  * Read-before-write: a region is never compared against an entry written
    earlier in the same run.
  * Full agent runs populate ``temp:trend_notes`` in session state for the
    curator (verified through a probe sub-agent, mirroring the fleet hand-off).
"""

from __future__ import annotations

import json

from google.adk.agents import BaseAgent, SequentialAgent
from google.adk.events import Event
from google.genai import types

from agents.historian import agent as ha
from agents.historian.agent import HistorianAgent, compute_trend
from agents.tools import firestore_tool

from _util import FleetHarness, final_text


def assessment(
    region_id: str,
    risk: str,
    assessed_at: str = "2026-08-01T00:00:00+00:00",
) -> dict:
    return {
        "region_id": region_id,
        "country": "Testland",
        "risk_level": risk,
        "explanation": "test explanation",
        "confidence": "Medium",
        "signals_used": ["admissions_pct_change"],
        "days_since_survey": 40,
        "assessed_at": assessed_at,
    }


def history_entry(
    region_id: str,
    risk: str,
    recorded_at: str = "2026-08-01T00:00:00+00:00",
) -> dict:
    """A persisted history entry: SignalAssessment + recorded_at."""
    return {**assessment(region_id, risk), "recorded_at": recorded_at}


class FakeHistoryStore:
    """In-memory stand-in for firestore_tool.read/write_assessment_history."""

    def __init__(self, docs: dict[str, dict] | None = None):
        self.docs = {r: json.loads(json.dumps(d)) for r, d in (docs or {}).items()}
        self.reads: list[str] = []
        self.writes: list[tuple[str, dict]] = []

    def read(self, region_id: str) -> dict | None:
        self.reads.append(region_id)
        doc = self.docs.get(region_id)
        return json.loads(json.dumps(doc)) if doc else None

    def write(self, region_id: str, data: dict) -> None:
        self.writes.append((region_id, json.loads(json.dumps(data))))
        self.docs[region_id] = json.loads(json.dumps(data))

    def doc(self, region_id: str) -> dict | None:
        return self.docs.get(region_id)


def patch_store(monkeypatch, store: FakeHistoryStore) -> None:
    monkeypatch.setattr(firestore_tool, "read_assessment_history", store.read)
    monkeypatch.setattr(firestore_tool, "write_assessment_history", store.write)


async def run_historian(
    store: FakeHistoryStore,
    assessments: list[dict],
    state_extra: dict | None = None,
) -> tuple[list[dict], list[str]]:
    harness = FleetHarness(HistorianAgent())
    await harness.create_session()
    await harness.run(
        state_delta={
            "temp:run_id": "hist-test-run",
            "temp:assessments": assessments,
            **(state_extra or {}),
        }
    )
    notes = json.loads(final_text(harness.final) or "[]")
    return notes, [e.author for e in harness.events if e.is_final_response()]


# ---------------------------------------------------------------------------
# Pure logic
# ---------------------------------------------------------------------------
def test_compute_trend_first_observation() -> None:
    note = compute_trend(assessment("fresh-01", "Stable"), [])
    assert note["region_id"] == "fresh-01"
    assert note["trend_direction"] == "first_observation"
    assert note["previous_risk_level"] is None
    assert note["current_risk_level"] == "Stable"
    assert note["runs_compared"] == 0


def test_compute_trend_directions() -> None:
    current = assessment("r1", "Watch")
    worsening = compute_trend(current, [history_entry("r1", "Stable")])
    assert worsening["trend_direction"] == "worsening"
    assert worsening["previous_risk_level"] == "Stable"

    improving = compute_trend(current, [history_entry("r1", "Urgent")])
    assert improving["trend_direction"] == "improving"
    assert improving["previous_risk_level"] == "Urgent"

    unchanged = compute_trend(current, [history_entry("r1", "Watch")])
    assert unchanged["trend_direction"] == "unchanged"
    assert unchanged["previous_risk_level"] == "Watch"


def test_compute_trend_compares_against_last_entry_only() -> None:
    entries = [
        history_entry("r1", "Stable", "2026-07-01T00:00:00+00:00"),
        history_entry("r1", "Urgent", "2026-07-02T00:00:00+00:00"),
    ]
    note = compute_trend(assessment("r1", "Watch"), entries)
    assert note["trend_direction"] == "improving"
    assert note["previous_risk_level"] == "Urgent"


def test_compute_trend_runs_compared_counts_prior_entries() -> None:
    one = compute_trend(
        assessment("r1", "Watch"), [history_entry("r1", "Stable")]
    )
    assert one["runs_compared"] == 1

    priors = [
        history_entry("r1", lvl, f"2026-07-{i + 1:02d}T00:00:00+00:00")
        for i, lvl in enumerate(["Stable", "Watch", "Urgent", "Stable", "Watch"])
    ]
    five = compute_trend(assessment("r1", "Urgent"), priors)
    assert len(priors) == ha.HISTORY_MAX_ENTRIES
    assert five["runs_compared"] == ha.HISTORY_MAX_ENTRIES


def test_append_to_history_trims_to_last_five() -> None:
    priors = [
        history_entry("r1", lvl, f"2026-07-{i + 1:02d}T00:00:00+00:00")
        for i, lvl in enumerate(["Stable", "Watch", "Urgent", "Stable", "Watch"])
    ]
    appended = ha._append_to_history(
        priors, history_entry("r1", "Urgent", "2026-08-10T00:00:00+00:00")
    )
    assert len(appended) == ha.HISTORY_MAX_ENTRIES == 5
    assert appended[0]["recorded_at"] == "2026-07-02T00:00:00+00:00"  # 07-01 dropped
    assert appended[-1] == history_entry("r1", "Urgent", "2026-08-10T00:00:00+00:00")


# ---------------------------------------------------------------------------
# Agent behavior against the mocked Firestore store
# ---------------------------------------------------------------------------
async def test_agent_first_observation_creates_history_doc(monkeypatch) -> None:
    store = FakeHistoryStore()
    patch_store(monkeypatch, store)

    notes, _ = await run_historian(store, [assessment("fresh-01", "Stable")])
    (note,) = notes
    assert note["trend_direction"] == "first_observation"
    assert note["previous_risk_level"] is None
    assert note["runs_compared"] == 0

    assert store.reads == ["fresh-01"]
    assert len(store.writes) == 1
    doc = store.doc("fresh-01")
    assert doc["region_id"] == "fresh-01"
    (entry,) = doc["entries"]
    assert entry["risk_level"] == "Stable"
    assert entry["region_id"] == "fresh-01"
    assert "recorded_at" in entry


async def test_agent_unchanged_against_prior_doc(monkeypatch) -> None:
    store = FakeHistoryStore(
        {
            "r1": {
                "region_id": "r1",
                "entries": [history_entry("r1", "Watch", "2026-07-20T00:00:00+00:00")],
            }
        }
    )
    patch_store(monkeypatch, store)

    notes, _ = await run_historian(store, [assessment("r1", "Watch")])
    (note,) = notes
    assert note["trend_direction"] == "unchanged"
    assert note["previous_risk_level"] == "Watch"
    assert note["runs_compared"] == 1

    doc = store.doc("r1")
    assert [e["risk_level"] for e in doc["entries"]] == ["Watch", "Watch"]


async def test_agent_read_before_write_same_region(monkeypatch) -> None:
    """Two assessments for one region: the second must not see the first's write."""
    store = FakeHistoryStore(
        {
            "r1": {
                "region_id": "r1",
                "entries": [history_entry("r1", "Stable", "2026-07-20T00:00:00+00:00")],
            }
        }
    )
    patch_store(monkeypatch, store)

    notes, _ = await run_historian(
        store, [assessment("r1", "Watch"), assessment("r1", "Watch")]
    )
    assert [n["trend_direction"] for n in notes] == ["worsening", "worsening"]
    assert [n["previous_risk_level"] for n in notes] == ["Stable", "Stable"]
    assert store.reads.count("r1") == 1  # baseline read once, never re-read post-write

    doc = store.doc("r1")
    assert [e["risk_level"] for e in doc["entries"]] == ["Stable", "Watch", "Watch"]


async def test_agent_trims_history_to_last_five(monkeypatch) -> None:
    priors = [
        history_entry("r1", lvl, f"2026-07-{i + 1:02d}T00:00:00+00:00")
        for i, lvl in enumerate(["Stable", "Watch", "Urgent", "Stable", "Watch"])
    ]
    store = FakeHistoryStore({"r1": {"region_id": "r1", "entries": priors}})
    patch_store(monkeypatch, store)

    notes, _ = await run_historian(store, [assessment("r1", "Urgent")])
    (note,) = notes
    assert note["runs_compared"] == ha.HISTORY_MAX_ENTRIES == 5

    doc = store.doc("r1")
    assert len(doc["entries"]) == ha.HISTORY_MAX_ENTRIES == 5
    assert doc["entries"][0]["recorded_at"] == "2026-07-02T00:00:00+00:00"  # oldest dropped
    assert doc["entries"][-1]["risk_level"] == "Urgent"  # this run's append


class _StateProbe(BaseAgent):
    """Trivial sub-agent that reports temp:trend_notes, like the curator would."""

    name: str = "probe"
    instructions: str = "Report the trend notes from session state."
    tools: list = []

    async def _run_async_impl(self, ctx):
        notes = ctx.session.state.get("temp:trend_notes", [])
        yield Event(
            author=self.name,
            content=types.Content(
                role="model", parts=[types.Part(text=json.dumps(notes))]
            ),
        )


async def test_agent_populates_trend_notes_in_session_state(monkeypatch) -> None:
    store = FakeHistoryStore(
        {
            "r1": {
                "region_id": "r1",
                "entries": [history_entry("r1", "Stable", "2026-07-20T00:00:00+00:00")],
            }
        }
    )
    patch_store(monkeypatch, store)

    fleet = SequentialAgent(
        name="historian_fleet", sub_agents=[HistorianAgent(), _StateProbe()]
    )
    harness = FleetHarness(fleet)
    await harness.create_session()
    await harness.run(
        state_delta={
            "temp:run_id": "hist-test-run",
            "temp:assessments": [assessment("r1", "Watch")],
        }
    )

    state_notes = json.loads(final_text(harness.final) or "[]")
    assert state_notes == [
        {
            "region_id": "r1",
            "previous_risk_level": "Stable",
            "current_risk_level": "Watch",
            "trend_direction": "worsening",
            "runs_compared": 1,
            "note": "Risk has escalated from Stable to Watch since the last assessment.",
        }
    ]