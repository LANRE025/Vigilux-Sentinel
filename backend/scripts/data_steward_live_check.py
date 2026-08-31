"""Live integration check for the Data Steward agent - NOT part of the pytest suite.

Connects to real Firestore and runs the real data steward path against the
current region_snapshots collection, printing how many (region, disease)
signals are flagged stale-enough-to-evaluate plus a couple of examples.

Requires ADC credentials and uses the real threshold from backend/.env
(DATA_STEWARD_STALENESS_THRESHOLD_DAYS, default 14 - inclusive).

Run from backend/:
    ..\\.venv\\Scripts\\python.exe scripts\\data_steward_live_check.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.data_steward.agent import collect_region_signals  # noqa: E402
from agents.tools import firestore_tool  # noqa: E402


def main() -> int:
    total = len(firestore_tool.read_region_snapshots())
    signals = collect_region_signals()
    print(f"region_snapshots docs: {total}")
    print(f"signals flagged (>= threshold, stale enough to evaluate): {len(signals)}")
    for sig in signals[:3]:
        print("example:", json.dumps(sig))
    return 0


if __name__ == "__main__":
    sys.exit(main())