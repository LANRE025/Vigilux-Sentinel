"""Application configuration for Vigilux Sentinel.

All fleet settings are read from environment variables or a local .env file.
See .env.example (at the backend/ root) for the full list of supported variables.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, overridable via environment or .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Identity / naming -------------------------------------------------
    APP_NAME: str = "vigilux-sentinel"
    FLEET_USER_ID: str = "fleet-runner"

    # --- Google Cloud ------------------------------------------------------
    GOOGLE_CLOUD_PROJECT: str = ""
    # Firestore database region. Kept separate from the Gemini Vertex location
    # on purpose: the two services require different values and must not be
    # driven by a single env var.
    FIRESTORE_REGION: str = "us-central1"
    FIRESTORE_DATABASE: str = ""

    # --- Gemini -------------------------------------------------------------
    # Gemini is called through Vertex AI and authenticated with Application
    # Default Credentials (gcloud auth application-default login). No API key
    # is required and none is read by the fleet code.
    GEMINI_MODEL: str = "gemini-3.5-flash"
    # gemini-3.5-flash is not published on every regional Vertex AI endpoint;
    # "global" (default) is the supported location.
    GEMINI_VERTEX_LOCATION: str = "global"
    # Optional, unused by default: a Gemini Developer API key. Kept so someone
    # can locally re-add the API-key path instead of Vertex AI if they choose;
    # nothing in the fleet reads it.
    GEMINI_API_KEY: str = ""

    # --- Fleet policy -------------------------------------------------------
    # Regions whose survey is older than this many days are pushed to the
    # risk-assessor for a SignalAssessment.
    SURVEY_STALENESS_THRESHOLD_DAYS: int = 30
    # When Gemini is unavailable or returns something unusable, fall back to a
    # deterministic heuristic so a fleet run can still complete.
    USE_HEURISTIC_FALLBACK: bool = True

    # --- Memory Bank (optional) --------------------------------------------
    # Set MEMORY_BANK_AGENT_ENGINE_ID to the name of a provisioned Vertex AI
    # Agent Engine (Memory Bank). When empty, a Firestore-backed rolling window
    # (last N assessments per region) is used instead.
    MEMORY_BANK_AGENT_ENGINE_ID: str = ""
    MEMORY_BANK_AGENT_ENGINE_LOCATION: str = "global"

    # --- Observability -------------------------------------------------------
    OTEL_CLOUD_TRACE_ENABLED: bool = True

    # --- Runtime -------------------------------------------------------------
    LOG_LEVEL: str = "INFO"
    HOST: str = "0.0.0.0"
    PORT: int = 8080


settings = Settings()