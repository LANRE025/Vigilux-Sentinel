"""Unit tests for the risk assessor agent.

Covers:
  * Gemini is called once per STALE region signal only (fresh are skipped).
  * A failing / unparseable Gemini response falls back to the deterministic
    heuristic and the per-region loop keeps running.
  * Structured output is finalized with authoritative fields from the region
    signal.
  * Bounded retry: one retry for parse failures (stricter prompt) and for
    transient API errors (identical prompt); non-retryable API errors are not
    retried; after the single retry fails, the existing fallback/raise path
    runs.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors as genai_errors

from agents.models.schemas import Confidence, RegionSignal, RiskLevel, SignalAssessment
from agents.risk_assessor import agent as ra
from agents.risk_assessor.agent import RiskAssessorAgent

from _util import FleetHarness, final_text


def _response(parsed=None, text=None):
    """A bare GenerateContentResponse stand-in carrying parsed/text."""

    return SimpleNamespace(parsed=parsed, text=text)


class FakeGemini:
    """Bare minimum of ``genai.Client`` touched by the fleet code.

    ``outcomes`` scripts a sequence of responses: each entry is either a
    response object (``parsed``/``text``) to return or an ``Exception``
    instance to raise, in order (the last entry repeats once exhausted). For
    backward compatibility, ``fail=True``/``fail_exc=`` behave like
    ``outcomes=[exception]`` and ``parsed/text`` like ``outcomes=[response]``.
    """

    def __init__(self, parsed=None, text=None, fail=False, fail_exc=None, outcomes=None):
        if outcomes is not None:
            self.outcomes = list(outcomes)
        elif fail:
            self.outcomes = [fail_exc or RuntimeError("gemini unavailable")]
        else:
            self.outcomes = [_response(parsed=parsed, text=text)]
        self.calls: list[dict] = []
        self.models = SimpleNamespace(generate_content=self._generate)

    def _generate(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes[min(len(self.calls) - 1, len(self.outcomes) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def signal(
    region_id: str = "region-a-01",
    stale_days: int = 40,
    pct: float = 8.0,
    funding_pct: float = 90.0,
    disease: str | None = None,
) -> RegionSignal:
    return RegionSignal(
        region=region_id,
        country="Testland",
        disease=disease,
        days_stale=stale_days,
        admissions_pct_change=pct,
        funding_pct_of_avg=funding_pct,
        evaluated_at="2026-07-01T00:00:00+00:00",
    )


async def _run_signals(harness, signals: list[RegionSignal] | list[dict]) -> None:
    payload = [s.model_dump(mode="json") for s in signals]
    await harness.create_session()
    await harness.run(
        state_delta={"temp:run_id": "ra-test-run", "temp:region_snapshots": payload}
    )


async def test_fresh_and_stale_selection(monkeypatch) -> None:
    """Only stale regions reach Gemini; an unparseable response falls back."""
    fake = FakeGemini(parsed=None, text=None)  # unusable -> heuristic fallback
    monkeypatch.setattr(ra, "_build_client", lambda: fake)

    region_signals = [
        signal("region-a-01", stale_days=45),
        signal("region-b-01", stale_days=5),  # fresh -> must be skipped
        signal("region-c-01", stale_days=70),
    ]
    harness = FleetHarness(RiskAssessorAgent())
    await _run_signals(harness, region_signals)

    assert fake.calls, "Gemini should have been called for stale regions"
    for call in fake.calls:
        content = call["contents"]
        assert "region-a-01" in content or "region-c-01" in content
        assert "region-b-01" not in content
    # 2 stale regions x (original call + one parse-failure retry): the fake is
    # unusable, so each region's first parse attempt is retried once before
    # falling through to the heuristic.
    assert len(fake.calls) == 4

    payload = json.loads(final_text(harness.final) or "[]")
    assert len(payload) == 2
    assert {a["region_id"] for a in payload} == {"region-a-01", "region-c-01"}
    assert payload[0]["days_since_survey"] == 45


async def test_boundary_inclusive_at_threshold(monkeypatch) -> None:
    """A signal at exactly the threshold (30 days) is included, not dropped."""
    fake = FakeGemini(parsed=None, text=None)  # unusable -> heuristic fallback
    monkeypatch.setattr(ra, "_build_client", lambda: fake)

    region_signals = [
        signal("region-at-01", stale_days=30),  # exactly threshold -> included
        signal("region-below-01", stale_days=29),  # just below -> skipped
    ]
    harness = FleetHarness(RiskAssessorAgent())
    await _run_signals(harness, region_signals)

    payload = json.loads(final_text(harness.final) or "[]")
    assert len(payload) == 1
    assert payload[0]["region_id"] == "region-at-01"
    # The at-threshold region must have been passed to Gemini (fake called)
    assert any("region-at-01" in c["contents"] for c in fake.calls)


async def test_gemini_structured_output_finalized(monkeypatch) -> None:
    """Structured assessment is used with authoritative fields overwritten."""
    model_assessment = SignalAssessment(
        region_id="stale-authoritative-value",
        country="Wrongland",
        risk_level=RiskLevel.WATCH,
        explanation="Admissions trending up, funding thinning.",
        confidence=Confidence.MEDIUM,
        signals_used=["admissions_pct_change", "funding_pct_of_avg"],
        days_since_survey=99,
        assessed_at="model-fabricated",
    )
    fake = FakeGemini(parsed=model_assessment)
    monkeypatch.setattr(ra, "_build_client", lambda: fake)

    result = ra.assess_region(signal("region-a-01", stale_days=40))

    assert result["region_id"] == "region-a-01"
    assert result["country"] == "Testland"
    assert result["days_since_survey"] == 40
    assert result["risk_level"] == "Watch"
    assert result["confidence"] == "Medium"
    assert result["assessed_at"]


def test_heuristic_fallback_reports_sensible_levels() -> None:
    """The deterministic heuristic flags extreme signals Urgent, healthy Stable."""
    extreme = signal("region-x-01", stale_days=80, pct=22.0, funding_pct=30.0)
    assert ra._assess_heuristically(extreme).risk_level == RiskLevel.URGENT

    healthy = signal("region-y-01", stale_days=3, pct=0.0, funding_pct=120.0)
    assert ra._assess_heuristically(healthy).risk_level == RiskLevel.STABLE


def test_heuristic_recalibrated_boundaries() -> None:
    """Funding- and age-only cases pin the recalibrated URGENT/WATCH cutoffs."""
    urgent_by_funding = signal("region-w-01", stale_days=10, pct=2.0, funding_pct=60.0)
    assert ra._assess_heuristically(urgent_by_funding).risk_level == RiskLevel.URGENT

    watch_by_funding = signal("region-v-01", stale_days=10, pct=2.0, funding_pct=80.0)
    assert ra._assess_heuristically(watch_by_funding).risk_level == RiskLevel.WATCH

    watch_by_age = signal("region-z-01", stale_days=75, pct=2.0, funding_pct=95.0)
    assert ra._assess_heuristically(watch_by_age).risk_level == RiskLevel.WATCH


async def test_hard_failure_with_without_fallback_policy(monkeypatch) -> None:
    """A real client error still completes the run when fallback is enabled."""
    fake = FakeGemini(fail=True)
    monkeypatch.setattr(ra, "_build_client", lambda: fake)
    monkeypatch.setattr(ra.settings, "USE_HEURISTIC_FALLBACK", True)

    harness = FleetHarness(RiskAssessorAgent())
    await _run_signals(harness, [signal("region-a-01", stale_days=45)])

    payload = json.loads(final_text(harness.final) or "[]")
    assert len(payload) == 1
    assert payload[0]["risk_level"], "fallback assessment should still be produced"


def _valid_assessment() -> SignalAssessment:
    return SignalAssessment(
        region_id="region-a-01",
        country="Testland",
        risk_level=RiskLevel.WATCH,
        explanation="Admissions trending up, funding thinning.",
        confidence=Confidence.MEDIUM,
        signals_used=["admissions_pct_change"],
        days_since_survey=40,
        assessed_at="model-time",
    )


STRICTER_PARSE_NOTE = "Your previous response could not be parsed as valid JSON"


# --- Bounded retry: parse failures -----------------------------------------
def test_parse_failure_retries_once_with_stricter_prompt() -> None:
    """First response unparseable -> second call MUST carry the stricter
    prompt (checked via the mock's call args, not just the final result)."""
    fake = FakeGemini(
        outcomes=[
            _response(parsed=None, text="not-json-at-all"),
            _response(parsed=_valid_assessment()),
        ]
    )

    result = ra._assess_with_gemini(signal("region-a-01", stale_days=40), fake)

    assert len(fake.calls) == 2
    first_prompt, second_prompt = fake.calls[0]["contents"], fake.calls[1]["contents"]
    assert STRICTER_PARSE_NOTE not in first_prompt
    assert STRICTER_PARSE_NOTE in second_prompt
    assert second_prompt.startswith(first_prompt)
    assert result.risk_level == RiskLevel.WATCH


async def test_parse_failure_twice_falls_to_heuristic_after_two_calls(monkeypatch) -> None:
    """Two unparseable responses -> heuristic fallback, but only AFTER two
    Gemini calls, not one."""
    fake = FakeGemini(
        outcomes=[
            _response(parsed=None, text="not-json"),
            _response(parsed=None, text="still-not-json"),
        ]
    )
    monkeypatch.setattr(ra, "_build_client", lambda: fake)
    monkeypatch.setattr(ra.settings, "USE_HEURISTIC_FALLBACK", True)

    harness = FleetHarness(RiskAssessorAgent())
    await _run_signals(harness, [signal("region-a-01", stale_days=45)])

    assert len(fake.calls) == 2
    payload = json.loads(final_text(harness.final) or "[]")
    assert len(payload) == 1
    assert payload[0]["risk_level"], "heuristic fallback should produce an assessment"


async def test_parse_failure_twice_raises_when_fallback_disabled(monkeypatch) -> None:
    """With the heuristic disabled, two unparseable responses raise - and the
    run must not make a third attempt."""
    fake = FakeGemini(
        outcomes=[
            _response(parsed=None, text=None),
            _response(parsed=None, text=None),
        ]
    )
    monkeypatch.setattr(ra, "_build_client", lambda: fake)
    monkeypatch.setattr(ra.settings, "USE_HEURISTIC_FALLBACK", False)

    harness = FleetHarness(RiskAssessorAgent())
    with pytest.raises(Exception):
        await _run_signals(harness, [signal("region-a-01", stale_days=45)])
    assert len(fake.calls) == 2


# --- Bounded retry: transient API errors -----------------------------------
def test_transient_rate_limit_retries_once_with_same_prompt() -> None:
    """429 rate-limit on first call -> retry with the IDENTICAL prompt, then
    succeed. Prompt equality across both calls is asserted (unlike the
    parse-failure path)."""
    rate_limited = genai_errors.ClientError(
        429, {"error": {"status": "RESOURCE_EXHAUSTED", "message": "rate limited"}}
    )
    fake = FakeGemini(
        outcomes=[rate_limited, _response(parsed=_valid_assessment())]
    )

    result = ra._assess_with_gemini(signal("region-a-01", stale_days=40), fake)

    assert len(fake.calls) == 2
    assert fake.calls[0]["contents"] == fake.calls[1]["contents"]
    assert result.risk_level == RiskLevel.WATCH


def test_transient_api_error_classification() -> None:
    """Classification is confirmed against the installed SDK's assumption of
    what is transient (408/429/500/502/503/504 + httpx timeouts/connects)."""
    transient = [
        genai_errors.ClientError(429, {"error": {"status": "RESOURCE_EXHAUSTED"}}),
        genai_errors.ClientError(408, {"error": {"status": "DEADLINE_EXCEEDED"}}),
        genai_errors.ServerError(500, {"error": {"status": "INTERNAL"}}),
        genai_errors.ServerError(503, {"error": {"status": "UNAVAILABLE"}}),
        genai_errors.ServerError(504, {"error": {"status": "DEADLINE_EXCEEDED"}}),
        httpx.TimeoutException("read timed out"),
    ]
    for exc in transient:
        assert ra._is_transient_api_error(exc), f"expected transient: {exc}"

    non_transient = [
        genai_errors.ClientError(400, {"error": {"status": "INVALID_ARGUMENT"}}),
        genai_errors.ClientError(403, {"error": {"status": "PERMISSION_DENIED"}}),
        genai_errors.ClientError(404, {"error": {"status": "NOT_FOUND"}}),
        genai_errors.ServerError(501, {"error": {"status": "NOT_IMPLEMENTED"}}),
        RuntimeError("unrelated failure"),
    ]
    for exc in non_transient:
        assert not ra._is_transient_api_error(exc), f"expected non-transient: {exc}"


# --- Bounded retry: non-retryable API errors -------------------------------
def test_non_retryable_permission_denied_calls_once(monkeypatch) -> None:
    """A permission-denied (403) error must NOT be retried - the regression
    test proving we do not waste a second round-trip on failures that will
    repeat identically."""
    denied = genai_errors.ClientError(
        403, {"error": {"status": "PERMISSION_DENIED", "message": "no access"}}
    )
    fake = FakeGemini(outcomes=[denied])
    monkeypatch.setattr(ra, "_build_client", lambda: fake)

    with pytest.raises(genai_errors.ClientError):
        ra.assess_region(signal("region-a-01", stale_days=45))

    assert len(fake.calls) == 1