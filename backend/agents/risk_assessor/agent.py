"""risk_assessor: produces a SignalAssessment per stale region.

Deterministic control flow: every region whose ``days_since_survey`` exceeds
the staleness threshold is handed to Gemini (one structured call per region,
returning a ``SignalAssessment`` with ``response_schema``). Regions that are
still fresh are skipped entirely - no tokens spent.

When Gemini is unavailable or unusable and ``USE_HEURISTIC_FALLBACK`` is set,
a deterministic heuristic produces the assessment so the run can complete.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from google.adk.agents import BaseAgent
from google.adk.events import Event
from google.genai import types

from ..config import settings
from ..models.schemas import Confidence, RegionSnapshot, RiskLevel, SignalAssessment
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


def _build_prompt(snapshot: RegionSnapshot) -> str:
    return (
        "You are the risk assessor for Vigilux Sentinel, a global outbreak-intelligence fleet.\n"
        "\n"
        "A field team recently submitted this region snapshot:\n"
        "\n"
        f"{json.dumps(snapshot.model_dump(mode='json'), indent=2)}\n"
        "\n"
        "Determine the risk level for this region's outbreak-control readiness:\n"
        "\n"
        "- Urgent: sharply rising admissions (e.g. admissions_pct_change >= +15), critically\n"
        "  low funding (well below the regional average), severely depleted staffing or supplies.\n"
        "- Watch: rising admissions, thinning funding, or a markedly ageing survey\n"
        "  (days_since_survey at or beyond the fleet threshold).\n"
        "- Stable: no concerning signals.\n"
        "\n"
        "Respond with a SignalAssessment: choose risk_level (Stable/Watch/Urgent), give a\n"
        "1-3 sentence explanation citing the concrete signals you weighed, and your\n"
        "confidence (Low/Medium/High). List the exact signal fields you used\n"
        '(e.g. "admissions_pct_change", "funding_usd", "staffing_count") in signals_used.\n'
        "The region_id, country, days_since_survey and assessed_at fields are set\n"
        "authoritatively by the fleet; only model the judgment fields: risk_level,\n"
        "explanation, confidence, signals_used."
    )


def _assess_with_gemini(snapshot: RegionSnapshot, client: Any) -> SignalAssessment:
    """One structured Gemini call for a single region."""
    response = client.models.generate_content(
        model=settings.GEMINI_MODEL,
        contents=_build_prompt(snapshot),
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=SignalAssessment,
            temperature=0.2,
        ),
    )
    parsed = response.parsed
    if parsed is None and getattr(response, "text", None):
        parsed = SignalAssessment.model_validate_json(response.text)
    if parsed is None:
        raise ValueError("Gemini returned no parseable SignalAssessment")
    return SignalAssessment.model_validate(parsed)


def _suggested_signals(snapshot: RegionSnapshot) -> list[str]:
    funding_ratio = (
        snapshot.funding_usd / snapshot.regional_avg_funding_usd
        if snapshot.regional_avg_funding_usd
        else 1.0
    )
    signals = ["days_since_survey", "admissions_pct_change"]
    if funding_ratio < 0.9:
        signals.append("funding_usd")
    if snapshot.staffing_count < 60:
        signals.append("staffing_count")
    if snapshot.supply_stock_units < 200:
        signals.append("supply_stock_units")
    return signals


def _assess_heuristically(snapshot: RegionSnapshot) -> SignalAssessment:
    """Deterministic fallback so the fleet completes without Gemini."""
    funding_ratio = (
        snapshot.funding_usd / snapshot.regional_avg_funding_usd
        if snapshot.regional_avg_funding_usd
        else 1.0
    )
    signals = _suggested_signals(snapshot)
    if (
        snapshot.admissions_pct_change >= 15.0
        or funding_ratio <= 0.7
        or snapshot.staffing_count < 30
    ):
        level, confidence = RiskLevel.URGENT, Confidence.MEDIUM
        explanation = (
            f"{snapshot.region_id} shows critical strain: "
            f"admissions +{snapshot.admissions_pct_change:.1f}%, funding ratio "
            f"{funding_ratio:.0%} of regional average."
        )
    elif (
        snapshot.days_since_survey >= 60
        or snapshot.admissions_pct_change >= 5.0
        or funding_ratio <= 0.85
        or snapshot.staffing_count < 60
    ):
        level, confidence = RiskLevel.WATCH, Confidence.MEDIUM
        explanation = (
            f"{snapshot.region_id} shows early warning signals "
            f"(admissions +{snapshot.admissions_pct_change:.1f}%, funding ratio "
            f"{funding_ratio:.0%}, survey {snapshot.days_since_survey}d old)."
        )
    else:
        level, confidence = RiskLevel.STABLE, Confidence.HIGH
        explanation = (
            f"{snapshot.region_id} shows no concerning signals: stable admissions, "
            f"adequate funding and staffing."
        )
    return SignalAssessment(
        region_id=snapshot.region_id,
        country=snapshot.country,
        risk_level=level,
        explanation=explanation,
        confidence=confidence,
        signals_used=signals,
        days_since_survey=snapshot.days_since_survey,
        assessed_at=_iso_now(),
    )


def assess_region(snapshot: RegionSnapshot) -> dict[str, Any]:
    """Assess one region, finalizing authoritative fields from the snapshot.

    Raises when Gemini fails and the heuristic fallback is disabled.
    """
    parsed = _assess_with_gemini(snapshot, _build_client())
    final = SignalAssessment(
        region_id=snapshot.region_id,
        country=snapshot.country,
        risk_level=parsed.risk_level,
        explanation=parsed.explanation,
        confidence=parsed.confidence,
        signals_used=parsed.signals_used or _suggested_signals(snapshot),
        days_since_survey=snapshot.days_since_survey,
        assessed_at=_iso_now(),
    )
    return final.model_dump(mode="json")


class RiskAssessorAgent(BaseAgent):
    """Fleet agent that produces a SignalAssessment per stale region."""

    name: str = AGENT_NAME
    tools: list[Any] = [assess_region]
    instructions: str = (
        "For every region whose days_since_survey exceeds the fleet's staleness "
        "threshold, call Gemini (structured SignalAssessment output) once per "
        "region. Fresh regions are skipped. Failures fall back to the "
        "deterministic heuristic when enabled."
    )

    async def _run_async_impl(self, ctx):
        run_id = ctx.session.state.get("temp:run_id", "unknown")
        raw_snapshots: list[dict] = ctx.session.state.get("temp:region_snapshots", [])
        threshold = settings.SURVEY_STALENESS_THRESHOLD_DAYS
        candidates = [
            RegionSnapshot(**raw)
            for raw in raw_snapshots
            if int(raw.get("days_since_survey", 0)) > threshold
        ]

        with observability.agent_span(AGENT_NAME, run_id=run_id) as handle:
            assessments: list[dict[str, Any]] = []
            for snapshot in candidates:
                try:
                    assessments.append(assess_region(snapshot))
                except Exception as exc:
                    if not settings.USE_HEURISTIC_FALLBACK:
                        handle.set_error(exc)
                        raise
                    logger.warning(
                        "Gemini assessment failed for %s (%s); using heuristic",
                        snapshot.region_id,
                        exc,
                    )
                    assessments.append(
                        _assess_heuristically(snapshot).model_dump(mode="json")
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