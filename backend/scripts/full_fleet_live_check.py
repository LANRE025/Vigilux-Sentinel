"""Live end-to-end check for the full four-agent fleet - NOT part of the pytest suite.

Runs the REAL, production-wired orchestrator (``build_orchestrator``) through the
same ADK Runner / session mechanism the fleet tests use (``tests/test_historian
.py``, ``tests/test_curator.py``: InMemorySessionService + Runner + state_delta),
but against REAL Firestore and REAL Gemini - no mocks, no HTTP layer. Session
state is seeded exactly like ``main.py``'s ``POST /fleet/run`` handler.

After the run it reads ``temp:fleet_report`` (final session state, falling back
to Curator's final Event payload, which carries the identical dict), prints the
report, verifies the curator-specified sort order, and cross-checks how many
regions the data steward read vs. flagged vs. how many actually reached the risk
assessor and got assessed.

Requires ADC credentials and uses the real thresholds from backend/.env
(DATA_STEWARD_STALENESS_THRESHOLD_DAYS, default 30 - inclusive).

Run from backend/:
    ..\\.venv\\Scripts\\python.exe scripts\\full_fleet_live_check.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google.adk import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402

from agents.config import settings  # noqa: E402
from agents.data_steward.agent import collect_region_signals  # noqa: E402
from agents.models.schemas import FLEET_AGENT_NAMES  # noqa: E402
from agents.orchestrator import build_orchestrator  # noqa: E402
from agents.tools import firestore_tool  # noqa: E402

TRIGGER_MESSAGE = (
    "Run the full Vigilux Sentinel fleet monitoring pass for all regions "
    "and return the FleetReport."
)

# Same severity ordering the curator sorts by.
_RANK = {"Urgent": 2, "Watch": 1, "Stable": 0}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sort_order_holds(assessments: list[dict]) -> bool:
    """Curator order: risk_level desc (Urgent/Watch/Stable), then
    days_since_survey desc within the same risk level."""
    for left, right in zip(assessments, assessments[1:]):
        if _RANK[left["risk_level"]] < _RANK[right["risk_level"]]:
            return False
        if (
            _RANK[left["risk_level"]] == _RANK[right["risk_level"]]
            and left["days_since_survey"] < right["days_since_survey"]
        ):
            return False
    return True


def _final_payload(events: list) -> dict | None:
    """Parse the FleetReport from Curator's final-response Event (as main.py does)."""
    final = next((e for e in reversed(events) if e.is_final_response()), None)
    if final is None or not (
        final.content and final.content.parts and final.content.parts[0].text
    ):
        return None
    return json.loads(final.content.parts[0].text)


async def _run(region_ids: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING)

    # Pre-run counts against real Firestore.
    total = len(firestore_tool.read_region_snapshots())
    flagged = collect_region_signals()
    print(f"data steward read (region_snapshots docs): {total}")
    print(
        "data steward flagged (>= DATA_STEWARD_STALENESS_THRESHOLD_DAYS="
        f"{settings.DATA_STEWARD_STALENESS_THRESHOLD_DAYS}, inclusive): {len(flagged)}"
    )

    if region_ids is not None:
        print(f"requested region_ids ({len(region_ids)}): {region_ids}")

    if len(flagged) > 0:
        print(f"expected to reach the risk-assessor: {len(flagged)}")

    run_id = uuid.uuid4().hex
    state_delta: dict[str, object] = {
        "temp:run_id": run_id,
        "temp:started_at": _iso_now(),
    }
    if region_ids:
        state_delta["temp:region_ids"] = region_ids

    session_service = InMemorySessionService()
    await session_service.create_session(
        app_name=settings.APP_NAME,
        user_id=settings.FLEET_USER_ID,
        session_id=run_id,
    )
    runner = Runner(
        app_name=settings.APP_NAME,
        agent=build_orchestrator(),
        session_service=session_service,
    )

    events = []
    try:
        async for event in runner.run_async(
            user_id=settings.FLEET_USER_ID,
            session_id=run_id,
            state_delta=state_delta,
            new_message=types.Content(
                role="user", parts=[types.Part(text=TRIGGER_MESSAGE)]
            ),
        ):
            events.append(event)
    except Exception as exc:  # noqa: BLE001 - report any mid-pipeline failure loudly
        done = sorted({e.author for e in events if e.is_final_response()})
        print(
            f"\nERROR: fleet run failed after agent(s): {', '.join(done) or 'none'} "
            f"(exception: {exc})"
        )
        traceback.print_exc()
        return 1

    # Read temp:fleet_report from final session state; ADK does not flush
    # in-place ctx.session.state mutations back to the stored session, so fall
    # back to Curator's final Event payload (the identical dict) when absent.
    report: dict | None = None
    source = "final-event"
    try:
        stored = await session_service.get_session(
            app_name=settings.APP_NAME,
            user_id=settings.FLEET_USER_ID,
            session_id=run_id,
        )
        saved = (stored.state or {}).get("temp:fleet_report") if stored else None
        if saved:
            report, source = saved, "session-state"
    except Exception:  # noqa: BLE001 - non-fatal, fall back to the event payload
        pass
    if report is None:
        report = _final_payload(events) or {}

    completed = sorted({e.author for e in events if e.is_final_response()})
    print(f"\nfleet run {report.get('run_id')} - agents completed: {', '.join(completed)}")
    print(f"  report source: {source}")
    print(f"  regions_evaluated: {report.get('regions_evaluated')}")
    print(f"  regions_flagged:   {report.get('regions_flagged')}")
    print(f"  started_at: {report.get('started_at')}")
    print(f"  completed_at: {report.get('completed_at')}")

    missing_ids = report.get("missing_region_ids") or []
    if missing_ids:
        print(f"  missing region_ids: {missing_ids}")

    assessments = report.get("assessments", [])
    print(f"\nassessments ({len(assessments)}), in report order:")
    for a in assessments:
        trend = (a.get("trend") or {}).get("trend_direction", "-")
        print(
            f"  {a['region_id']:<24} {a['risk_level']:<7} "
            f"days_since_survey={a['days_since_survey']:<4} trend={trend}"
        )

    if assessments:
        ok = _sort_order_holds(assessments)
        print(
            f"\nsort order check: {'PASS' if ok else 'FAIL'} "
            "(Urgent first, then Watch, then Stable; within each level "
            "days_since_survey descending)"
        )
    else:
        ok = True
        print("\nsort order check: PASS (no assessments to sort)")

    print(f"  region vs total: flagged {len(flagged)} of {total} docs; "
          f"assessed {len(assessments)}")
    pipeline_ok = True
    if len(flagged) > 0 and len(assessments) == 0:
        print(
            "\nPIPELINE WARNING: 0 assessments were produced although the data "
            "steward flagged >0 stale regions - the report is misleading.\n"
            "Likely causes: (a) a region_ids filter filtered everything out "
            "(all requested ids missing/unstale), or (b) temp:region_snapshots "
            "received no signals at all. Inspect the emitted signals before "
            "trusting this run."
        )
        pipeline_ok = False

    expected_agents = set(FLEET_AGENT_NAMES)
    if completed and set(completed) != expected_agents:
        missing = expected_agents - set(completed)
        print(f"\nAGENT WARNING: expected {sorted(expected_agents)} but only "
              f"{sorted(completed)} completed; missing {sorted(missing)}")
        pipeline_ok = False

    return 0 if (ok and pipeline_ok) else 1


def main() -> int:
    args = sys.argv[1:]
    region_ids = list(args) if args else None
    if region_ids is None and "--help" in args or "-h" in args:
        print("usage: full_fleet_live_check.py [region_id ...]")
        print("  (comma-free; optional region_ids; omit for the full fleet)")
        return 0
    return asyncio.run(_run(region_ids))


if __name__ == "__main__":
    sys.exit(main())