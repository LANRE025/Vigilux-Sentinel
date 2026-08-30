"""Unit tests for the data steward agent.

Verifies that the agent reads region snapshots from Firestore (via a mocked
read) and hands them to the fleet, most recently surveyed first, with no LLM
involved.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from agents.data_steward.agent import DataStewardAgent
from agents.tools import firestore_tool

from _util import FleetHarness, final_text

SNAPSHOT_TEMPLATE = {
    "region_id": "region-{n}-01",
    "country": "Testland",
    "last_survey_at": None,  # set per test
    "days_since_survey": 0,
    "admissions_last_14d": [3] * 14,
    "admissions_pct_change": 1.0,
    "funding_usd": 100000.0,
    "staffing_count": 80,
    "supply_stock_units": 500,
    "regional_avg_funding_usd": 100000.0,
}


def _snap(n: str, days_ago: int) -> dict:
    data = dict(SNAPSHOT_TEMPLATE)
    data["region_id"] = f"region-{n}-01"
    data["last_survey_at"] = (
        datetime.now(timezone.utc) - timedelta(days=days_ago)
    ).isoformat()
    data["days_since_survey"] = days_ago
    return data


def canonical_snapshots() -> list[dict]:
    # Two stale, one fresh, deliberately shuffled at the source.
    return [_snap("b", 50), _snap("a", 5), _snap("c", 90)]


async def test_steward_reads_and_orders_snapshots(monkeypatch) -> None:
    monkeypatch.setattr(
        firestore_tool,
        "read_region_snapshots",
        lambda: [dict(s) for s in canonical_snapshots()],
    )

    harness = FleetHarness(DataStewardAgent())
    await harness.create_session()
    await harness.run(state_delta={"temp:run_id": "ds-test-run"})

    payload = json.loads(final_text(harness.final) or "[]")
    assert harness.final is not None and harness.final.author == "data_steward"
    # The agent passes through Firestore's ordering (most recent survey first
    # is enforced inside firestore_tool.read_region_snapshots).
    assert [s["region_id"] for s in payload] == [
        "region-b-01",
        "region-a-01",
        "region-c-01",
    ]
    assert all(s["days_since_survey"] in (5, 50, 90) for s in payload)


async def test_firestore_read_orders_most_recent_first(monkeypatch) -> None:
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
                    FakeDoc(_snap("b", 50)),
                    FakeDoc(_snap("a", 5)),
                    FakeDoc(_snap("c", 90)),
                ]
            )

        def collection(self, _name):
            return self

    monkeypatch.setattr(firestore_tool, "_client", lambda: FakeQuery())
    docs = firestore_tool.read_region_snapshots()
    assert [d["region_id"] for d in docs] == [
        "region-a-01",
        "region-b-01",
        "region-c-01",
    ]


async def test_steward_handles_empty_firestore(monkeypatch) -> None:
    monkeypatch.setattr(firestore_tool, "read_region_snapshots", lambda: [])

    harness = FleetHarness(DataStewardAgent())
    await harness.create_session()
    await harness.run()

    assert json.loads(final_text(harness.final) or "[]") == []