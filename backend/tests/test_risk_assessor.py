"""Unit tests for the risk assessor agent.

Covers:
  * Gemini is called once per STALE region only (fresh regions are skipped).
  * A failing / unparseable Gemini response falls back to the deterministic
    heuristic and the per-region loop keeps running.
  * Structured output is finalized with authoritative fields from the snapshot.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from agents.models.schemas import Confidence, RegionSnapshot, RiskLevel, SignalAssessment
from agents.risk_assessor import agent as ra
from agents.risk_assessor.agent import RiskAssessorAgent

from _util import FleetHarness, final_text


class FakeGemini:
    """Bare minimum of ``genai.Client`` touched by the fleet code."""

    def __init__(self, parsed=None, text=None, fail=False):
        self.parsed = parsed
        self.text = text
        self.fail = fail
        self.calls: list[dict] = []
        self.models = SimpleNamespace(generate_content=self._generate)

    def _generate(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("gemini unavailable")
        return SimpleNamespace(parsed=self.parsed, text=self.text)


def snapshot(
    region_id: str = "region-a-01",
    stale_days: int = 40,
    pct: float = 8.0,
    funding: float = 90000.0,
    staffing: int = 50,
) -> RegionSnapshot:
    return RegionSnapshot(
        region_id=region_id,
        country="Testland",
        last_survey_at="2026-07-01T00:00:00+00:00",
        days_since_survey=stale_days,
        admissions_last_14d=[5] * 14,
        admissions_pct_change=pct,
        funding_usd=funding,
        staffing_count=staffing,
        supply_stock_units=400,
        regional_avg_funding_usd=100000.0,
    )


async def _run_snapshots(harness, snapshots: list[RegionSnapshot] | list[dict]) -> None:
    payload = [s.model_dump(mode="json") for s in snapshots]
    await harness.create_session()
    await harness.run(
        state_delta={"temp:run_id": "ra-test-run", "temp:region_snapshots": payload}
    )


async def test_fresh_and_stale_selection(monkeypatch) -> None:
    """Only stale regions reach Gemini; an unparseable response falls back."""
    fake = FakeGemini(parsed=None, text=None)  # unusable -> heuristic fallback
    monkeypatch.setattr(ra, "_build_client", lambda: fake)

    snapshots = [
        snapshot("region-a-01", stale_days=45),
        snapshot("region-b-01", stale_days=5),  # fresh -> must be skipped
        snapshot("region-c-01", stale_days=70),
    ]
    harness = FleetHarness(RiskAssessorAgent())
    await _run_snapshots(harness, snapshots)

    assert fake.calls, "Gemini should have been called for stale regions"
    for call in fake.calls:
        content = call["contents"]
        assert "region-a-01" in content or "region-c-01" in content
        assert "region-b-01" not in content
    assert len(fake.calls) == 2

    payload = json.loads(final_text(harness.final) or "[]")
    assert len(payload) == 2
    assert {a["region_id"] for a in payload} == {"region-a-01", "region-c-01"}
    assert payload[0]["days_since_survey"] == 45


async def test_gemini_structured_output_finalized(monkeypatch) -> None:
    """Structured assessment is used with authoritative fields overwritten."""
    model_assessment = SignalAssessment(
        region_id="stale-authoritative-value",
        country="Wrongland",
        risk_level=RiskLevel.WATCH,
        explanation="Admissions trending up, funding thinning.",
        confidence=Confidence.MEDIUM,
        signals_used=["admissions_pct_change", "funding_usd"],
        days_since_survey=99,
        assessed_at="model-fabricated",
    )
    fake = FakeGemini(parsed=model_assessment)
    monkeypatch.setattr(ra, "_build_client", lambda: fake)

    result = ra.assess_region(snapshot("region-a-01", stale_days=40))

    assert result["region_id"] == "region-a-01"
    assert result["country"] == "Testland"
    assert result["days_since_survey"] == 40
    assert result["risk_level"] == "Watch"
    assert result["confidence"] == "Medium"
    assert result["assessed_at"]


def test_heuristic_fallback_reports_sensible_levels() -> None:
    """The deterministic heuristic flags extreme snapshots Urgent, healthy Stable."""
    extreme = snapshot("region-x-01", stale_days=80, pct=22.0, funding=30000.0, staffing=10)
    assert ra._assess_heuristically(extreme).risk_level == RiskLevel.URGENT

    healthy = snapshot("region-y-01", stale_days=3, pct=0.0, funding=120000.0, staffing=90)
    assert ra._assess_heuristically(healthy).risk_level == RiskLevel.STABLE


async def test_hard_failure_with_without_fallback_policy(monkeypatch) -> None:
    """A real client error still completes the run when fallback is enabled."""
    fake = FakeGemini(fail=True)
    monkeypatch.setattr(ra, "_build_client", lambda: fake)
    monkeypatch.setattr(ra.settings, "USE_HEURISTIC_FALLBACK", True)

    harness = FleetHarness(RiskAssessorAgent())
    await _run_snapshots(harness, [snapshot("region-a-01", stale_days=45)])

    payload = json.loads(final_text(harness.final) or "[]")
    assert len(payload) == 1
    assert payload[0]["risk_level"], "fallback assessment should still be produced"