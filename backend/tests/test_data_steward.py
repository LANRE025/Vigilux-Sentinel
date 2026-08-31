"""Unit tests for the data steward agent - fixtures only, no live Firestore.

Covers:
  * Threshold semantics: above (flagged), below (skipped), and exactly at the
    boundary - documented as INCLUSIVE (a region exactly N days stale IS
    evaluated; staleness is integer days, floored).
  * The canonical ``RegionSignal`` output contract: exact key set, exact types.
  * Funding percentage is DERIVED from absolute dollars, never assumed.
  * Staleness is recomputed against the run-time clock, never the seed-time
    ``days_since_survey`` value.
  * The agent itself runs through the real google-adk ``Runner``.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from google.adk.agents import BaseAgent, SequentialAgent
from google.adk.events import Event
from google.genai import types

from agents.data_steward import agent as ds
from agents.data_steward.agent import DataStewardAgent
from agents.tools import firestore_tool

from _util import FleetHarness, final_text

# Fixed "now" so boundary arithmetic is deterministic (no clock races).
NOW = datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc)

CANONICAL_FIELDS = {
    "region",
    "country",
    "disease",
    "days_stale",
    "admissions_pct_change",
    "funding_pct_of_avg",
    "evaluated_at",
}


def _doc(
    region_id="region-x-01",
    country="Testland",
    disease="COVID-19",
    days_old=10,
    admissions_pct_change=17.0,
    funding_usd=52000.0,
    regional_avg_funding_usd=100000.0,
) -> dict:
    """A raw region_snapshots document shaped like live Firestore data."""
    data = {
        "region_id": region_id,
        "country": country,
        "last_survey_at": (NOW - timedelta(days=days_old)).isoformat(),
        # Seed-time staleness value: present but NEVER authoritative.
        "days_since_survey": days_old,
        "admissions_last_14d": [3] * 14,
        "admissions_pct_change": admissions_pct_change,
        "funding_usd": funding_usd,
        "staffing_count": 10,
        "supply_stock_units": 50,
        "regional_avg_funding_usd": regional_avg_funding_usd,
    }
    if disease is not None:
        data["disease"] = disease
    return data


def _run(documents: list[dict], threshold: int = 14):
    """Run the pure signal builder against fixtures at the fixed clock."""
    return ds.build_region_signals(documents, threshold_days=threshold, now=NOW)


def _ids(signals: list[dict]) -> set[str]:
    return {s["region"] for s in signals}


# --- Threshold semantics --------------------------------------------------
def test_region_above_threshold_is_flagged():
    signals = _run([_doc(region_id="region-stale-01", days_old=30)])
    assert _ids(signals) == {"region-stale-01"}


def test_region_below_threshold_is_skipped():
    assert _run([_doc(region_id="region-fresh-01", days_old=5)]) == []


def test_boundary_is_inclusive():
    # Exactly 30 days old -> evaluated. 29 days old -> skipped.
    # Staleness is integer whole days (floored), so 29d23h59m == 29 days.
    at_boundary = _run([_doc(region_id="region-at-01", days_old=30)], threshold=30)
    just_below = _run([_doc(region_id="region-below-01", days_old=29)], threshold=30)
    assert _ids(at_boundary) == {"region-at-01"}
    assert just_below == []


# --- Canonical output contract --------------------------------------------
def test_output_matches_canonical_schema_exactly():
    docs = [
        _doc(region_id="region-a-01", days_old=30, disease="COVID-19"),
        _doc(region_id="region-b-01", days_old=25, disease=None),
    ]
    signals = _run(docs, threshold=14)

    assert len(signals) == 2
    for s in signals:
        assert set(s) == CANONICAL_FIELDS, f"unexpected keys: {set(s).symmetric_difference(CANONICAL_FIELDS)}"

    s = signals[0]
    assert s["region"] == "region-a-01" and isinstance(s["region"], str)
    assert s["country"] == "Testland" and isinstance(s["country"], str)
    assert s["disease"] == "COVID-19" and isinstance(s["disease"], str)
    assert s["days_stale"] == 30 and isinstance(s["days_stale"], int)
    assert isinstance(s["admissions_pct_change"], float)
    assert isinstance(s["funding_pct_of_avg"], float)
    assert s["evaluated_at"] == NOW.isoformat() and isinstance(s["evaluated_at"], str)
    # Region-level doc (no disease in storage) -> explicit None, never dropped.
    assert signals[1]["disease"] is None
    assert signals[1]["days_stale"] == 25


# --- Derived values -------------------------------------------------------
def test_funding_pct_is_derived_from_absolute_dollars():
    docs = [
        _doc(region_id="region-quarter-01", days_old=20, funding_usd=25000.0),
        _doc(region_id="region-half-01", days_old=20, funding_usd=50000.0),
        _doc(region_id="region-noavg-01", days_old=20, funding_usd=40000.0, regional_avg_funding_usd=0.0),
    ]
    by_id = {s["region"]: s for s in _run(docs)}
    assert by_id["region-quarter-01"]["funding_pct_of_avg"] == 25.0
    assert by_id["region-half-01"]["funding_pct_of_avg"] == 50.0
    assert by_id["region-noavg-01"]["funding_pct_of_avg"] == 0.0


def test_staleness_recomputed_against_now_not_stored_value():
    doc = _doc(region_id="region-old-01", days_old=31)
    doc["days_since_survey"] = 2  # stale seed-time value: must be ignored
    signals = _run([doc])
    assert signals[0]["days_stale"] == 31


def test_bad_survey_date_raises_instead_of_guessing():
    doc = _doc(region_id="region-bad-01", days_old=20)
    doc["last_survey_at"] = "not-a-date"
    with pytest.raises(ValueError, match="last_survey_at"):
        _run([doc])


# --- Agent through the real Runner ----------------------------------------
async def test_agent_emits_canonical_signals_for_stale_docs(monkeypatch):
    docs = [
        _doc(region_id="region-a-01", days_old=45, disease="COVID-19"),
        _doc(region_id="region-b-01", days_old=5, disease="HIV"),  # too fresh
    ]
    monkeypatch.setattr(firestore_tool, "read_region_snapshots", lambda: docs)

    harness = FleetHarness(DataStewardAgent())
    await harness.create_session()
    await harness.run(state_delta={"temp:run_id": "ds-test"})

    payload = json.loads(final_text(harness.final) or "[]")
    assert [s["region"] for s in payload] == ["region-a-01"]
    for s in payload:
        assert set(s) == CANONICAL_FIELDS
    assert harness.final is not None and harness.final.author == "data_steward"


async def test_agent_empty_firestore_yields_empty_signals(monkeypatch):
    monkeypatch.setattr(firestore_tool, "read_region_snapshots", lambda: [])
    harness = FleetHarness(DataStewardAgent())
    await harness.create_session()
    await harness.run()
    assert json.loads(final_text(harness.final) or "[]") == []


# --- Region-id selection (POST /fleet/run region_ids parameter) -----------
async def test_agent_region_ids_subset(monkeypatch):
    """Passing temp:region_ids filters to only those regions."""
    docs = [
        _doc(region_id="region-a-01", days_old=45, disease="COVID-19"),
        _doc(region_id="region-b-01", days_old=40, disease="HIV"),
        _doc(region_id="region-c-01", days_old=35, disease="Malaria"),
    ]
    monkeypatch.setattr(firestore_tool, "read_region_snapshots", lambda: docs)

    harness = FleetHarness(DataStewardAgent())
    await harness.create_session()
    await harness.run(
        state_delta={
            "temp:run_id": "ds-test",
            "temp:region_ids": ["region-a-01", "region-c-01"],
        }
    )
    payload = json.loads(final_text(harness.final) or "[]")
    ids = {s["region"] for s in payload}
    assert ids == {"region-a-01", "region-c-01"}
    assert "region-b-01" not in ids


async def test_agent_invalid_region_ids_surfaced(monkeypatch):
    """Invalid region_ids are skipped and appear in temp:missing_region_ids."""
    docs = [
        _doc(region_id="region-a-01", days_old=45, disease="COVID-19"),
        _doc(region_id="region-b-01", days_old=40, disease="HIV"),
    ]
    monkeypatch.setattr(firestore_tool, "read_region_snapshots", lambda: docs)

    class _StateProbe(BaseAgent):
        name: str = "probe"
        instructions: str = "report data steward state"
        tools: list = []

        async def _run_async_impl(self, ctx):
            result = {
                "signals": ctx.session.state.get("temp:region_snapshots", []),
                "missing": ctx.session.state.get("temp:missing_region_ids", []),
            }
            yield Event(
                author=self.name,
                content=types.Content(
                    role="model", parts=[types.Part(text=json.dumps(result))]
                ),
            )

    fleet = SequentialAgent(
        name="ds_fleet", sub_agents=[DataStewardAgent(), _StateProbe()]
    )
    harness = FleetHarness(fleet)
    await harness.create_session()
    await harness.run(
        state_delta={
            "temp:run_id": "ds-test",
            "temp:region_ids": ["region-a-01", "region-ghost-01"],
        }
    )

    payload = json.loads(final_text(harness.final) or "{}")
    assert [s["region"] for s in payload["signals"]] == ["region-a-01"]
    assert payload["missing"] == ["region-ghost-01"]


async def test_agent_no_region_ids_full_fleet(monkeypatch):
    """Without temp:region_ids the full fleet is processed (unchanged behavior)."""
    docs = [
        _doc(region_id="region-a-01", days_old=45, disease="COVID-19"),
        _doc(region_id="region-b-01", days_old=40, disease="HIV"),
    ]
    monkeypatch.setattr(firestore_tool, "read_region_snapshots", lambda: docs)

    harness = FleetHarness(DataStewardAgent())
    await harness.create_session()
    await harness.run(state_delta={"temp:run_id": "ds-test"})
    payload = json.loads(final_text(harness.final) or "[]")
    assert {s["region"] for s in payload} == {"region-a-01", "region-b-01"}


# --- firestore_tool compat shim (still used by the agent) -----------------
async def test_read_region_snapshots_orders_most_recent_first(monkeypatch):
    """firestore_tool.read_region_snapshots sorts most recently surveyed first."""

    class FakeDoc:
        def __init__(self, data):
            self._d = data

        def to_dict(self):
            return self._d

    class FakeQuery:
        def stream(self):
            return iter(
                [
                    FakeDoc(_doc(region_id="region-old-01", days_old=50, disease="HIV")),
                    FakeDoc(_doc(region_id="region-new-01", days_old=5, disease=None)),
                    FakeDoc(_doc(region_id="region-mid-01", days_old=90, disease="Malaria")),
                ]
            )

        def collection(self, _name):
            return self

    monkeypatch.setattr(firestore_tool, "_client", lambda: FakeQuery())
    docs = firestore_tool.read_region_snapshots()
    assert [d["region_id"] for d in docs] == [
        "region-new-01",
        "region-old-01",
        "region-mid-01",
    ]