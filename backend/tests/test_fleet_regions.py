"""Tests for GET /fleet/regions.

Confirms the endpoint is a fast, cheap read of available regions that
provably does NOT trigger any part of the assessment pipeline (no fleet
run, no data-steward/risk-assessor invocation).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

import main as main_mod
from main import app
from agents.tools import firestore_tool

client = TestClient(app)

_DOCS = [
    {
        "region_id": "region-a-01",
        "country": "Testland",
        "disease": "COVID-19",
    },
    {"region_id": "region-b-01", "country": "Testland"},  # region-level, no disease
]


def test_fleet_regions_returns_picker_rows(monkeypatch) -> None:
    """Returns exactly the requested shape: region_id + display_name."""
    monkeypatch.setattr(
        firestore_tool,
        "read_collection",
        lambda name: _DOCS if name == "region_snapshots" else _DOCS,
    )

    resp = client.get("/fleet/regions")

    assert resp.status_code == 200
    assert resp.json() == [
        {"region_id": "region-b-01", "display_name": "Testland"},
        {"region_id": "region-a-01", "display_name": "Testland / COVID-19"},
    ]


def test_fleet_regions_does_not_trigger_pipeline(monkeypatch) -> None:
    """The picker never starts the fleet: patch every pipeline entry point so
    it FAILS loudly if invoked, then confirm the endpoint still succeeds."""
    fired: list[str] = []

    def _guard(name):
        def _impl(*a, **k):
            fired.append(name)
            raise AssertionError(f"assessment pipeline entry {name} ran for a picker read")

        return _impl

    # Anything that would indicate the assessment pipeline was started.
    monkeypatch.setattr(main_mod, "build_orchestrator", _guard("build_orchestrator"))
    monkeypatch.setattr(main_mod, "fleet_run", _guard("fleet_run"))
    monkeypatch.setattr(
        firestore_tool, "read_region_snapshots", _guard("read_region_snapshots")
    )

    # The picker's own read still resolves (fast path) so the endpoint answers.
    monkeypatch.setattr(
        firestore_tool,
        "read_collection",
        lambda name: [
            {"region_id": "region-x-01", "country": "Atlantica", "disease": "Dengue"}
        ],
    )

    resp = client.get("/fleet/regions")

    assert resp.status_code == 200
    assert resp.json() == [
        {"region_id": "region-x-01", "display_name": "Atlantica / Dengue"}
    ]
    assert fired == [], f"assessment pipeline was invoked for a picker read: {fired}"
