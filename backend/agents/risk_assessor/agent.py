"""risk_assessor: produces a SignalAssessment per stale region signal.

Deterministic control flow: every region signal whose ``days_stale`` meets or
exceeds the staleness threshold is handed to Gemini (one structured call per region,
returning a ``SignalAssessment`` with ``response_schema``). Each call gets
exactly ONE bounded retry - a stricter prompt when the response could not be
parsed, or the identical prompt on a transient API error - before the failure
is surfaced. Signals that are still fresh are skipped entirely - no tokens
spent.

The agent consumes the data steward's canonical ``RegionSignal`` (region,
days_stale, admissions_pct_change, funding_pct_of_avg, optional disease) as
its input contract - not the raw region_snapshots storage shape.

When Gemini is unavailable or unusable and ``USE_HEURISTIC_FALLBACK`` is set,
a deterministic heuristic produces the assessment so the run can complete.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from google.adk.agents import BaseAgent
from google.adk.events import Event
from google.genai import errors as genai_errors
from google.genai import types

from ..config import settings
from ..models.schemas import Confidence, RegionSignal, RiskLevel, SignalAssessment
from ..tools import observability

logger = logging.getLogger(__name__)

AGENT_NAME = "risk_assessor"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_client():
    """Gemini client via Vertex AI, authenticated with Application Default
    Credentials. gemini-3.5-flash must be reached through the global Vertex
    location (GEMINI_VERTEX_LOCATION); no API key is used."""
    from google import genai

    return genai.Client(
        vertexai=True,
        project=settings.GOOGLE_CLOUD_PROJECT or None,
        location=settings.GEMINI_VERTEX_LOCATION,
    )


def _build_prompt(signal: RegionSignal) -> str:
    return (
        "You are the risk assessor for Vigilux Sentinel, a global outbreak-intelligence fleet.\n"
        "\n"
        "A field team recently submitted this region signal:\n"
        "\n"
        f"{json.dumps(signal.model_dump(mode='json'), indent=2)}\n"
        "\n"
        "Determine the risk level for this region's outbreak-control readiness:\n"
        "\n"
        "- Urgent: sharply rising admissions (e.g. admissions_pct_change >= +15), or\n"
        "  funding_pct_of_avg well below 100% (funding at a fraction of the regional\n"
        "  average - critical underfunding).\n"
        "- Watch: rising admissions, thinning funding (funding_pct_of_avg noticeably\n"
        "  below 100%), or a markedly ageing survey (days_stale at or beyond the\n"
        "  fleet threshold).\n"
        "- Stable: no concerning signals.\n"
        "\n"
        "The disease field is optional and may be absent (region-level signal); factor\n"
        "it into the judgment only when present.\n"
        "\n"
        "Respond with a SignalAssessment: choose risk_level (Stable/Watch/Urgent), give a\n"
        "1-3 sentence explanation citing the concrete signals you weighed, and your\n"
        "confidence (Low/Medium/High). List the exact signal fields you used\n"
        '(e.g. "admissions_pct_change", "funding_pct_of_avg", "disease") in signals_used.\n'
        "The region_id, country, days_since_survey and assessed_at fields are set\n"
        "authoritatively by the fleet; only model the judgment fields: risk_level,\n"
        "explanation, confidence, signals_used."
    )


class _ParseFailure(Exception):
    """Gemini's response could not be parsed as a valid SignalAssessment."""


# HTTP status codes where a retry can plausibly help. Mirrors the Google GenAI
# SDK's own classification (_api_client._RETRY_HTTP_STATUS_CODES: 408/429/500/
# 502/503/504), so we stay in sync with what the SDK itself treats as transient.
_TRANSIENT_HTTP_CODES = (408, 429, 500, 502, 503, 504)


def _is_transient_api_error(exc: Exception) -> bool:
    """True for rate-limit / 5xx / timeout-style errors worth retrying as-is.

    Confirmed against the installed google.genai SDK (errors.py +
    _api_client.py): HTTP error responses raise ``APIError`` subclasses
    (``ClientError`` for 4xx, ``ServerError`` for 5xx) carrying a numeric
    ``code``, and transport timeouts surface as ``httpx.TimeoutException`` /
    ``httpx.ConnectError`` (the SDK's own ``_HTTPX_TRANSIENT_EXC``). Everything
    else - e.g. auth failures, permission denied, model not found - will fail
    identically on retry and must NOT be retried.
    """
    if isinstance(exc, genai_errors.APIError):
        return exc.code in _TRANSIENT_HTTP_CODES
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError)):
        return True
    return False


def _response_text(response: Any) -> str | None:
    """Extract raw text from a GenerateContentResponse, tolerating SDKs whose
    ``.text`` property raises when there is no text candidate."""
    try:
        return response.text
    except (AttributeError, ValueError):
        return None


def _call_gemini_once(signal: RegionSignal, client: Any, prompt: str) -> SignalAssessment:
    """One structured Gemini call; raises ``_ParseFailure`` if the response
    cannot be interpreted as a ``SignalAssessment``."""
    response = client.models.generate_content(
        model=settings.GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=SignalAssessment,
            temperature=0.2,
        ),
    )
    parsed = response.parsed
    if parsed is None and _response_text(response):
        try:
            parsed = SignalAssessment.model_validate_json(_response_text(response))
        except Exception as exc:
            raise _ParseFailure(str(exc)) from exc
    if parsed is None:
        raise _ParseFailure("Gemini returned no parseable SignalAssessment")
    return SignalAssessment.model_validate(parsed)


def _assess_with_gemini(signal: RegionSignal, client: Any) -> SignalAssessment:
    """One structured Gemini call for a single region, with exactly one
    bounded retry for parse failures or transient API errors. Non-retryable
    API errors propagate immediately without a wasted second call."""
    base_prompt = _build_prompt(signal)
    try:
        return _call_gemini_once(signal, client, base_prompt)
    except _ParseFailure:
        stricter_prompt = base_prompt + (
            "\n\nYour previous response could not be parsed as valid JSON "
            "matching the required schema. Respond with ONLY the JSON "
            "object — no markdown code fences, no commentary, no extra text."
        )
        return _call_gemini_once(signal, client, stricter_prompt)
    except Exception as exc:
        if _is_transient_api_error(exc):
            return _call_gemini_once(signal, client, base_prompt)
        raise


def _suggested_signals(signal: RegionSignal) -> list[str]:
    signals = ["days_stale", "admissions_pct_change"]
    if signal.funding_pct_of_avg < 90:
        signals.append("funding_pct_of_avg")
    if signal.disease is not None:
        signals.append("disease")
    return signals


def _assess_heuristically(signal: RegionSignal) -> SignalAssessment:
    """Deterministic fallback so the fleet completes without Gemini."""
    signals = _suggested_signals(signal)
    if (
        signal.admissions_pct_change >= 15.0
        or signal.funding_pct_of_avg <= 70
    ):
        level, confidence = RiskLevel.URGENT, Confidence.MEDIUM
        explanation = (
            f"{signal.region} shows critical strain: "
            f"admissions +{signal.admissions_pct_change:.1f}%, funding "
            f"{signal.funding_pct_of_avg:.0f}% of regional average."
        )
    elif (
        signal.days_stale >= 60
        or signal.admissions_pct_change >= 5.0
        or signal.funding_pct_of_avg <= 85
    ):
        level, confidence = RiskLevel.WATCH, Confidence.MEDIUM
        explanation = (
            f"{signal.region} shows early warning signals "
            f"(admissions +{signal.admissions_pct_change:.1f}%, funding "
            f"{signal.funding_pct_of_avg:.0f}% of regional average, "
            f"survey {signal.days_stale}d old)."
        )
    else:
        level, confidence = RiskLevel.STABLE, Confidence.HIGH
        explanation = (
            f"{signal.region} shows no concerning signals: stable admissions, "
            f"funding close to the regional average, fresh survey."
        )
    return SignalAssessment(
        region_id=signal.region,
        country=signal.country,
        risk_level=level,
        explanation=explanation,
        confidence=confidence,
        signals_used=signals,
        days_since_survey=signal.days_stale,
        assessed_at=_iso_now(),
    )


def assess_region(signal: RegionSignal) -> dict[str, Any]:
    """Assess one region signal, finalizing authoritative fields from it.

    Raises when Gemini fails and the heuristic fallback is disabled.
    """
    parsed = _assess_with_gemini(signal, _build_client())
    final = SignalAssessment(
        region_id=signal.region,
        country=signal.country,
        risk_level=parsed.risk_level,
        explanation=parsed.explanation,
        confidence=parsed.confidence,
        signals_used=parsed.signals_used or _suggested_signals(signal),
        days_since_survey=signal.days_stale,
        assessed_at=_iso_now(),
    )
    return final.model_dump(mode="json")


class RiskAssessorAgent(BaseAgent):
    """Fleet agent that produces a SignalAssessment per stale region signal."""

    name: str = AGENT_NAME
    tools: list[Any] = [assess_region]
    instructions: str = (
        "For every region signal whose days_stale meets or exceeds the fleet's "
        "threshold, call Gemini (structured SignalAssessment output) once per "
        "region, allowing exactly one bounded retry when a response is "
        "unparseable or a transient API error occurs. Fresh regions are "
        "skipped. Failures fall back to the deterministic heuristic when "
        "enabled."
    )

    async def _run_async_impl(self, ctx):
        run_id = ctx.session.state.get("temp:run_id", "unknown")
        raw_snapshots: list[dict] = ctx.session.state.get("temp:region_snapshots", [])
        threshold = settings.SURVEY_STALENESS_THRESHOLD_DAYS
        candidates = [
            RegionSignal(**raw)
            for raw in raw_snapshots
            if int(raw.get("days_stale", 0)) >= threshold
        ]

        with observability.agent_span(AGENT_NAME, run_id=run_id) as handle:
            assessments: list[dict[str, Any]] = []
            for signal in candidates:
                try:
                    assessments.append(assess_region(signal))
                except Exception as exc:
                    if not settings.USE_HEURISTIC_FALLBACK:
                        handle.set_error(exc)
                        raise
                    logger.warning(
                        "Gemini assessment failed for %s (%s); using heuristic",
                        signal.region,
                        exc,
                    )
                    assessments.append(
                        _assess_heuristically(signal).model_dump(mode="json")
                    )
            ctx.session.state["temp:assessments"] = assessments
            handle.set_region_count(len(candidates))
            yield Event(
                author=self.name,
                content=types.Content(
                    role="model",
                    parts=[types.Part(text=json.dumps(assessments, indent=2) or "[]")],
                ),
            )