r"""Live-Firestore smoke test for the shared access layer.

Deliberately NOT part of the pytest suite - this hits a real Firestore
database with live credentials and would be flaky / polluting in CI. Run it
on demand from the backend/ directory:

    ..\.venv\Scripts\python.exe scripts\smoke_test_firestore.py

Credentials come from Application Default Credentials plus, optionally,
GOOGLE_CLOUD_PROJECT / FIRESTORE_DATABASE via backend/.env or the shell.

It exercises the doc-id-keyed layout: the smoke document uses the fixed ID
``smoke-test-region`` (so reruns upsert in place), round-trips through
read_document, then reports the region_snapshots collection size. The smoke
document is removed afterwards so a live collection stays clean.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.tools import firestore_tool  # noqa: E402

DOC_ID = "smoke-test-region"


def main() -> int:
    payload = {
        "region_id": DOC_ID,
        "country": "Smoke-Testland",
        # Kept at "now / 0 days since survey" so this doc never tripping a
        # staleness threshold and quietly feeds future fleet runs.
        "last_survey_at": datetime.now(timezone.utc).isoformat(),
        "days_since_survey": 0,
        "admissions_last_14d": [0] * 14,
        "admissions_pct_change": 0.0,
    }

    try:
        firestore_tool.write_document("region_snapshots", DOC_ID, payload)

        round_tripped = firestore_tool.read_document("region_snapshots", DOC_ID)
        assert round_tripped == payload, (
            f"round-trip mismatch:\n  wrote {payload}\n  read  {round_tripped}"
        )

        all_snapshots = firestore_tool.read_collection("region_snapshots")
        print(f"region_snapshots count: {len(all_snapshots)}")
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 1
    finally:
        try:  # best-effort cleanup so the live collection stays unpolluted
            firestore_tool._client().collection("region_snapshots").document(DOC_ID).delete()
            print(f"cleaned up smoke document '{DOC_ID}'")
        except Exception as exc:  # cleanup failure must not flip the result
            print(f"WARN: could not clean up smoke document: {exc}")
        firestore_tool.reset_client()  # drop the cached client for a clean re-run

    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())