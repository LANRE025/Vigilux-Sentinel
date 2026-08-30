"""Firestore persistence layer for the Vigilux Sentinel fleet.

Collection layout and document ID scheme
----------------------------------------
* ``region_snapshots``  - source data. Documents are keyed by the literal
  ``region_id`` (written by data/seed_regions.py), which keeps seeding
  idempotent on reruns and lets the data steward / curator address a specific
  region directly instead of querying by field.
* ``fleet_runs``        - one completed FleetReport per run, keyed by the
  run_id (a UUID the curator generates).
* ``run_observability`` - per-agent telemetry for a run, keyed by run_id.
* ``run_log``           - one entry per completed run, with AUTO-generated
  document IDs: each line is a fresh, unrelated record with no natural key to
  dedupe on (the one place auto IDs are correct).
* ``assessment_history`` - optional Memory Bank fallback (not built yet). If
  used, key it by ``region_id`` with per-region history as an array field or
  subcollection - this layout deliberately does not preclude that.

The public access layer (``read_collection`` / ``read_document`` /
``write_document`` / ``append_log``) is generic: the collection name is always
explicit, and everything is returned as plain dicts, so read-only agents
(data steward) and read/write agents (curator) share one entry point. Errors
are normalized to ``FirestoreError`` so tools surface a clean message instead
of a raw SDK stack trace. All functions are synchronous (the
google-cloud-firestore client is sync) and are mocked at the client boundary
in the unit tests.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Optional

from ..config import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _client():
    """Lazily built, cached Firestore client.

    Constructed from ``settings.GOOGLE_CLOUD_PROJECT``. If
    ``settings.FIRESTORE_DATABASE`` is a non-empty string it is passed as the
    ``database`` kwarg; if it is empty the kwarg is omitted entirely so the
    client uses the ``(default)`` database - passing an empty string is NOT
    the same as omitting it.
    """
    from google.cloud import firestore

    kwargs: dict[str, Any] = {}
    if settings.GOOGLE_CLOUD_PROJECT:
        kwargs["project"] = settings.GOOGLE_CLOUD_PROJECT
    if settings.FIRESTORE_DATABASE:
        kwargs["database"] = settings.FIRESTORE_DATABASE
    return firestore.Client(**kwargs)


def reset_client() -> None:
    """Drop the cached client (used by tests, the seed script and the smoke test)."""
    _client.cache_clear()


class FirestoreError(RuntimeError):
    """A Firestore operation failed (connectivity, permissions, or SDK error)."""


# ---------------------------------------------------------------------------
# Generic access layer (shared by read-only and read/write agents)
# ---------------------------------------------------------------------------
def read_collection(collection: str) -> list[dict[str, Any]]:
    """Return every document in ``collection`` as plain dicts (unsorted)."""
    try:
        docs = [
            doc.to_dict() or {}
            for doc in _client().collection(collection).stream()
        ]
    except Exception as exc:  # normalize SDK/network errors for tool callers
        raise FirestoreError(f"Failed to read collection '{collection}': {exc}") from exc
    return docs


def read_document(collection: str, doc_id: str) -> dict[str, Any] | None:
    """Return a single document by ID, or None if it does not exist."""
    try:
        doc = _client().collection(collection).document(doc_id).get()
    except Exception as exc:
        raise FirestoreError(f"Failed to read document '{collection}/{doc_id}': {exc}") from exc
    return doc.to_dict() if doc.exists else None


def write_document(collection: str, doc_id: str, data: dict[str, Any]) -> None:
    """Upsert ``data`` at an explicit document ID.

    Uses ``.set()`` rather than ``.add()`` so document IDs stay deterministic;
    use ``append_log`` when an auto-generated ID is wanted.
    """
    try:
        _client().collection(collection).document(doc_id).set(data)
    except Exception as exc:
        raise FirestoreError(f"Failed to write document '{collection}/{doc_id}': {exc}") from exc


def append_log(collection: str, data: dict[str, Any]) -> None:
    """Append a new document with an AUTO-generated ID (run_log style records)."""
    try:
        _client().collection(collection).document().set(data)
    except Exception as exc:
        raise FirestoreError(f"Failed to append document to '{collection}': {exc}") from exc


# ---------------------------------------------------------------------------
# Fleet-specific accessors (thin compat shims over the generic layer)
# ---------------------------------------------------------------------------
def read_region_snapshots() -> list[dict[str, Any]]:
    """Return all region snapshots (doc id == region_id), most recently surveyed first."""
    docs = read_collection("region_snapshots")
    docs.sort(key=lambda d: d.get("last_survey_at", ""), reverse=True)
    return docs


def write_fleet_report(report: dict[str, Any]) -> str:
    """Persist a FleetReport under fleet_runs/<run_id>. Returns the run id."""
    run_id = report["run_id"]
    write_document("fleet_runs", run_id, report)
    logger.info("Persisted fleet report for run %s", run_id)
    return run_id


def get_latest_fleet_run() -> Optional[dict[str, Any]]:
    """Return the most recently completed fleet run, or None."""
    runs = [d for d in read_collection("fleet_runs") if d.get("completed_at")]
    return max(runs, key=lambda d: d["completed_at"]) if runs else None


def write_run_observability(run_id: str, records: list[dict[str, Any]]) -> None:
    """Persist per-agent telemetry for a run under run_observability/<run_id>."""
    write_document("run_observability", run_id, {"run_id": run_id, "records": records})


def get_run_observability(run_id: str) -> Optional[dict[str, Any]]:
    """Return the persisted observability doc for a run, or None."""
    return read_document("run_observability", run_id)


def append_run_log(entry: dict[str, Any]) -> str:
    """Append a registry log entry; returns its auto-generated doc id.

    Like ``append_log`` but returns the generated id for callers that want it.
    """
    ref = _client().collection("run_log").document()
    try:
        ref.set(entry)
    except Exception as exc:
        raise FirestoreError(f"Failed to append registry log entry: {exc}") from exc
    return ref.id


def get_latest_run_log_entry() -> Optional[dict[str, Any]]:
    """Return the most recent registry log entry, or None."""
    entries = [d for d in read_collection("run_log") if d.get("run_timestamp")]
    return max(entries, key=lambda d: d["run_timestamp"]) if entries else None