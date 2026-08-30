"""Fleet orchestrator: the SequentialAgent that owns the four fleet sub-agents.

The orchestrator itself performs no LLM inference. It delegates the monitoring
pass to the sub-agents in strict order; each sub-agent passes its output to the
next via ``temp:*`` session state:
"""

from __future__ import annotations

from google.adk.agents import SequentialAgent

from .curator.agent import CuratorAgent
from .data_steward.agent import DataStewardAgent
from .historian.agent import HistorianAgent
from .risk_assessor.agent import RiskAssessorAgent

ORCHESTRATOR_NAME = "vigilux_orchestrator"


def build_orchestrator() -> SequentialAgent:
    """Construct the four-agent fleet under the SequentialAgent root."""
    return SequentialAgent(
        name=ORCHESTRATOR_NAME,
        description=(
            "Root fleet agent for Vigilux Sentinel. Runs the full regional "
            "monitoring pass in strict sequence: data-steward reads all region "
            "snapshots, risk-assessor produces SignalAssessments for stale "
            "regions, historian computes trends with the Memory Bank, and "
            "curator assembles + persists the FleetReport."
        ),
        sub_agents=[
            DataStewardAgent(),
            RiskAssessorAgent(),
            HistorianAgent(),
            CuratorAgent(),
        ],
    )