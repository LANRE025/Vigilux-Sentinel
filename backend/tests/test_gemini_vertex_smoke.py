r"""Gemini / Vertex AI smoke tests.

* ``test_build_client_uses_vertexai_global`` is offline: it asserts the fleet
  constructs a Vertex AI client (never the Developer-API ``api_key`` path) at
  the configured location (``global`` for gemini-3.5-flash).
* ``test_gemini_3_5_flash_via_adc_global`` is a live smoke test, skipped by
  default. Run it to confirm real Application Default Credentials authenticate
  a call to ``gemini-3.5-flash`` through the global Vertex AI location:

      $env:RUN_GEMINI_LIVE='1'
      ..\.venv\Scripts\python.exe -m pytest tests/test_gemini_vertex_smoke.py -v
"""

from __future__ import annotations

import os

import pytest

import google.genai as genai
from agents.risk_assessor import agent as ra
from agents.config import settings


def test_build_client_uses_vertexai_global(monkeypatch):
    captured: dict = {}

    def fake_client(**kwargs) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(genai, "Client", fake_client)

    ra._build_client()

    assert captured.get("vertexai") is True
    assert captured.get("project") == settings.GOOGLE_CLOUD_PROJECT or None
    assert captured.get("location") == "global"
    assert captured.get("location") == settings.GEMINI_VERTEX_LOCATION
    assert "api_key" not in captured


@pytest.mark.skipif(
    os.environ.get("RUN_GEMINI_LIVE") != "1",
    reason="live Vertex AI call; set RUN_GEMINI_LIVE=1 to run",
)
def test_gemini_3_5_flash_via_adc_global():
    client = genai.Client(
        vertexai=True,
        project=settings.GOOGLE_CLOUD_PROJECT or None,
        location=settings.GEMINI_VERTEX_LOCATION,
    )
    resp = client.models.generate_content(
        model=settings.GEMINI_MODEL,
        contents="Reply with exactly the word OK.",
    )
    text = resp.text or ""
    assert text.strip().upper() == "OK"