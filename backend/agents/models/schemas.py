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


class RegionSnapshot(BaseModel):
    """One region's most recent field snapshot, read by the data steward."""

    region_id: str
    country: str
    last_survey_at: str = Field(description="ISO 8601 timestamp of the field survey")
    days_since_survey: int = Field(ge=0)
    admissions_last_14d: list[int] = Field(description="Daily confirmed admissions, last 14 days")
    admissions_pct_change: float = Field(description="Percent change in admissions vs prior period")
    funding_usd: float
    staffing_count: int = Field(ge=0)
    supply_stock_units: int = Field(ge=0)
    regional_avg_funding_usd: float


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
    runs_compared: int = Field(ge=1)
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