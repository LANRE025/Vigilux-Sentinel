"""Memory Bank access for the Vigilux Sentinel fleet.

The historian uses the Memory Bank to recall the previous assessment for a
region before this run's assessment, then stores the new one.

Two implementations are provided behind a common interface:

1. ``VertexAiMemoryBank`` - the real Agent Engine (Memory Bank) API. Enabled by
   setting ``MEMORY_BANK_AGENT_ENGINE_ID`` in the environment. The
   google-cloud-aiplatform ``vertexai`` client is imported lazily so the rest
   of the SDK does not depend on it.

2. ``FirestoreFallbackMemoryBank`` - a compact per-region rolling window
   (last ``MAX_HISTORY_PER_REGION`` assessments) stored in the
   ``assessment_history`` Firestore collection. This is the default so the
   fleet works without provisioning an Agent Engine; it implements the same
   recall/store contract without needing a composite index.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Optional

from ..config import settings
from . import firestore_tool

logger = logging.getLogger(__name__)

COLLECTION = "assessment_history"
MAX_HISTORY_PER_REGION = 10
_APP_SCOPE = "vigilux-sentinel"


class MemoryBankClient:
    """Common recall/store contract used by the historian."""

    def recall_latest(self, region_id: str) -> Optional[dict[str, Any]]:
        """Return the most recent assessment for the region, or None."""
        raise NotImplementedError

    def store(self, region_id: str, assessment: dict[str, Any]) -> None:
        """Persist an assessment for the region."""
        raise NotImplementedError

    def history_size(self, region_id: str) -> int:
        """Number of remembered assessments for the region (bounded)."""
        raise NotImplementedError


class FirestoreFallbackMemoryBank(MemoryBankClient):
    """Default Memory Bank: rolling window per region in Firestore."""

    def _history(self, region_id: str) -> list[dict[str, Any]]:
        doc = firestore_tool._client().collection(COLLECTION).document(region_id).get()
        return list((doc.to_dict() or {}).get("history") or [])

    def recall_latest(self, region_id: str) -> Optional[dict[str, Any]]:
        history = self._history(region_id)
        latest = history[-1]["assessment"] if history else None
        return latest

    def store(self, region_id: str, assessment: dict[str, Any]) -> None:
        history = self._history(region_id)
        history.append(
            {
                "stored_at": datetime.now(timezone.utc).isoformat(),
                "assessment": assessment,
            }
        )
        history = history[-MAX_HISTORY_PER_REGION:]
        ref = firestore_tool._client().collection(COLLECTION).document(region_id)
        ref.set(
            {
                "region_id": region_id,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "history": history,
            }
        )

    def history_size(self, region_id: str) -> int:
        return len(self._history(region_id))


class VertexAiMemoryBank(MemoryBankClient):
    """Real Agent Engine (Memory Bank) implementation.

    Scopes each region's memories under ``user_id=f"region:{region_id}"`` so
    the same engine instance serves every region independently.
    """

    def __init__(self, project: str, location: str, engine_id: str) -> None:
        import vertexai  # lazily imported so core SDK has no hard dependency

        self._client = vertexai.Client(project=project, location=location)
        self._name = f"reasoningEngines/{engine_id}" if "reasoningEngines/" not in engine_id else engine_id

    def _scope(self, region_id: str) -> dict[str, str]:
        return {"app_name": _APP_SCOPE, "user_id": f"region:{region_id}"}

    @staticmethod
    def _fact_of(memory: Any) -> Optional[str]:
        inner = getattr(memory, "memory", None)
        if inner is not None:
            return getattr(inner, "fact", None)
        return getattr(memory, "fact", None)

    @staticmethod
    def _updated_at(memory: Any) -> Optional[str]:
        inner = getattr(memory, "memory", None) or memory
        return getattr(inner, "last_update_time", None) or getattr(inner, "update_time", None) or ""

    def recall_latest(self, region_id: str) -> Optional[dict[str, Any]]:
        page = list(
            self._client.agent_engines.memories.retrieve(
                name=self._name, scope=self._scope(region_id)
            ).page
        )
        if not page:
            return None
        newest = max(page, key=self._updated_at)
        fact = self._fact_of(newest)
        if not fact:
            return None
        try:
            data = json.loads(fact)
        except (TypeError, json.JSONDecodeError):
            logger.warning("Ignoring unparseable memory fact for region %s", region_id)
            return None
        return data if isinstance(data, dict) else None

    def store(self, region_id: str, assessment: dict[str, Any]) -> None:
        self._client.agent_engines.memories.create(
            name=self._name,
            fact=json.dumps(assessment),
            scope=self._scope(region_id),
        )

    def history_size(self, region_id: str) -> int:
        page = self._client.agent_engines.memories.retrieve(
            name=self._name, scope=self._scope(region_id)
        ).page
        return len(list(page))


@lru_cache(maxsize=1)
def get_memory_bank() -> MemoryBankClient:
    """Factory: the real Agent Engine when configured, else the fallback."""
    engine_id = (settings.MEMORY_BANK_AGENT_ENGINE_ID or "").strip()
    if engine_id:
        logger.info("Using Vertex AI Agent Engine Memory Bank: %s", engine_id)
        return VertexAiMemoryBank(
            project=settings.GOOGLE_CLOUD_PROJECT,
            location=settings.MEMORY_BANK_AGENT_ENGINE_LOCATION or "global",
            engine_id=engine_id,
        )
    logger.info("Using Firestore fallback Memory Bank")
    return FirestoreFallbackMemoryBank()