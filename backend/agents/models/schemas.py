"""Pydantic schemas shared by the Vigilux Sentinel fleet agents."""

from __future__ import annotations

import enum
from typing import Optional

from pydantic import BaseModel, Field


FLEET_AGENT_NAMES: list[str] = ["data_steward", "risk_assessor", "historian", "curator"]


class RiskLevel(str, enum.Enum):
    STABLE = "Stable"
    WATCH = "Watch"
    URGENT = "Urgent"


class Confidence(str, enum.Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"


class TrendDirection(str, enum.Enum):
    IMPROVING = "improving"
    WORSENING = "worsening"
    UNCHANGED = "unchanged"
    FIRST_OBSERVATION = "first_observation"


class RegionSignal(BaseModel):
    """Canonical per-(region, disease) signal emitted by the data steward.

    This is the fleet's input contract for downstream agents (e.g. the risk
    assessor), independent of whatever the raw region_snapshots storage field
    names happen to be. The data steward is the ONLY producer of this shape.
    """

    region: str
    country: str
    disease: Optional[str] = None  # absent on region-level (non-disease) docs
    days_stale: int = Field(ge=0, description="Whole days stale at run time")
    admissions_pct_change: float
    funding_pct_of_avg: float = Field(ge=0, description="funding_usd as % of regional average")
    evaluated_at: str = Field(description="ISO 8601 UTC timestamp of the signal")


class SignalAssessment(BaseModel):
    """Rich structured assessment produced per stale region."""

    region_id: str
    country: str
    risk_level: RiskLevel
    explanation: str = Field(description="1-3 sentence rationale citing chosen signals")
    confidence: Confidence
    signals_used: list[str] = Field(default_factory=list)
    days_since_survey: int = Field(ge=0)
    assessed_at: str = Field(description="ISO 8601 timestamp of the assessment")


class TrendNote(BaseModel):
    """Historian note comparing this run's assessment to the stored baseline."""

    region_id: str
    previous_risk_level: Optional[RiskLevel] = None
    current_risk_level: RiskLevel
    trend_direction: TrendDirection
    runs_compared: int = Field(ge=0, description="prior entries examined; 0 on first observation")
    note: str


class ReportAssessment(SignalAssessment):
    """A SignalAssessment enriched with its TrendNote."""

    trend: Optional[TrendNote] = None


class FleetReport(BaseModel):
    """Final output of the curator, persisted to Firestore and returned by the API."""

    run_id: str
    started_at: str
    completed_at: str
    regions_evaluated: int
    regions_flagged: int
    assessments: list[ReportAssessment] = Field(default_factory=list)
    missing_region_ids: list[str] = Field(
        default_factory=list,
        description="Requested region_ids not found in the data source (empty when no filter was applied)",
    )


class PerAgentTiming(BaseModel):
    """Timing/telemetry record for one agent in a fleet run."""

    agent: str
    started_at: str
    ended_at: str
    duration_ms: float
    regions_processed: int = 0
    error: Optional[str] = None


class RunLogEntry(BaseModel):
    """Registry log entry appended by the curator at the end of each run."""

    run_id: str
    run_timestamp: str
    agents: list[str]
    outcome: str = Field(description='"pass" or "fail"')
    regions_evaluated: int = 0
    regions_flagged: int = 0
    error: Optional[str] = None


class FleetStatus(BaseModel):
    """Response model for GET /fleet/status."""

    run_id: Optional[str] = None
    latest_run: Optional[FleetReport] = None
    agent_timings: list[PerAgentTiming] = Field(default_factory=list)
    registry_entry: Optional[RunLogEntry] = None
    message: Optional[str] = None