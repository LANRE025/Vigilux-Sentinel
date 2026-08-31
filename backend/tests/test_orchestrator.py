"""Import-time guard for the fleet orchestrator wiring.

The fleets' probe tests (test_historian / test_curator) build their own inline
``SequentialAgent`` sequences, so nothing exercised ``build_orchestrator()``
directly - which is how the earlier syntax error in orchestrator.py slipped
through uncaught. This test makes construction part of the suite, and proves
the ``region_ids`` selection feature flows through the full four-agent fleet
end to end.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from agents.models.schemas import Confidence, RiskLevel, SignalAssessment
from agents.risk_assessor import agent as ra
from agents.orchestrator import ORCHESTRATOR_NAME, build_orchestrator
from agents.tools import firestore_tool

from _util import FleetHarness, final_text


def test_build_orchestrator_constructs_the_four_agent_fleet() -> None:
    orchestrator = build_orchestrator()
    assert orchestrator is not None
    assert orchestrator.name == ORCHESTRATOR_NAME
    assert [a.name for a in orchestrator.sub_agents] == [
        "data_steward",
        "risk_assessor",
        "historian",
        "curator",
    ]


def _signal_assessment(region_id: str, stale_days: int) -> SignalAssessment:
    return SignalAssessment(
        region_id=region_id,
        country="Testland",
        risk_level=RiskLevel.WATCH,
        explanation="admissions up, funding thin",
        confidence=Confidence.MEDIUM,
        signals_used=["admissions_pct_change"],
        days_since_survey=stale_days,
        assessed_at="model-time",
    )


class _FakeGemini:
    """Stand-in for ra._build_client that returns a valid assessment for any
    region signal it is handed."""

    def __init__(self):
        self.calls: list[str] = []
        self.models = SimpleNamespace(generate_content=self._generate)

    def _generate(self, **kwargs):
        content = kwargs["contents"]
        self.calls.append(content)
        region = "unknown"
        line = next((ln for ln in content.splitlines() if '"region"' in ln), "")
        if line:
            region = line.split(":", 1)[1].strip().strip('",')
        stale = 40
        line2 = next((ln for ln in content.splitlines() if '"days_stale"' in ln), "")
        if line2:
            stale = int(line2.split(":", 1)[1].strip().strip('",'))
        return SimpleNamespace(
            parsed=_signal_assessment(region, stale),
            text=None,
        )


def _fleet_doc(
    region_id: str,
    country: str = "Testland",
    disease: str | None = "COVID-19",
    days_old: int = 45,
    admissions_pct_change: float = 12.0,
    funding_usd: float = 52000.0,
    regional_avg_funding_usd: float = 100000.0,
) -> dict:
    return {
        "region_id": region_id,
        "country": country,
        "disease": disease,
        "last_survey_at": "2026-07-15T00:00:00+00:00",
        "days_since_survey": days_old,
        "admissions_last_14d": [5] * 14,
        "admissions_pct_change": admissions_pct_change,
        "funding_usd": funding_usd,
        "staffing_count": 50,
        "supply_stock_units": 400,
        "regional_avg_funding_usd": regional_avg_funding_usd,
    }


async def test_fleet_region_ids_flows_end_to_end(monkeypatch) -> None:
    """A region_ids subset flows through all four agents unmodified; invalid
    ids surface in the report as missing_region_ids (never crash the run)."""
    docs = [
        _fleet_doc("region-a-01"),
        _fleet_doc("region-b-01"),
        _fleet_doc("region-c-01", disease=None),  # region-level signal
    ]
    monkeypatch.setattr(firestore_tool, "read_region_snapshots", lambda: docs)
    monkeypatch.setattr(
        firestore_tool, "read_assessment_history", lambda region_id: []
    )
    monkeypatch.setattr(
        firestore_tool, "write_assessment_history", lambda *a, **k: None
    )
    monkeypatch.setattr(
        firestore_tool, "write_fleet_report", lambda payload: None
    )
    monkeypatch.setattr(
        firestore_tool, "write_run_observability", lambda *a, **k: None
    )
    monkeypatch.setattr(
        firestore_tool, "append_run_log_entry", lambda *a, **k: None
    )
    fake = _FakeGemini()
    monkeypatch.setattr(ra, "_build_client", lambda: fake)

    fleet = build_orchestrator()
    harness = FleetHarness(fleet)
    await harness.create_session()
    await harness.run(
        state_delta={
            "temp:run_id": "orchestrator-e2e",
            "temp:started_at": "2026-08-01T00:00:00Z",
            # valid: region-a-01, region-c-01 (both present); invalid: region-ghost-01
            "temp:region_ids": ["region-a-01", "region-c-01", "region-ghost-01"],
        }
    )

    report = json.loads(final_text(harness.final) or "{}")
    assessed_ids = {a["region_id"] for a in report.get("assessments", [])}
    # Only the two requested, existing regions are assessed - region-b-01 is NOT.
    assert assessed_ids == {"region-a-01", "region-c-01"}
    assert "region-b-01" not in assessed_ids
    # Invalid requested id surfaced (not silently swallowed), run still completed.
    assert report.get("missing_region_ids") == ["region-ghost-01"]
    assert report.get("regions_evaluated") == 2
    # Gemini only ever saw the two requested regions.
    for call in fake.calls:
        assert "region-b-01" not in call