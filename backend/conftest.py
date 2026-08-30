"""Shared pytest fixtures and the single-agent run harness.

The harness runs an agent (or the whole orchestrator) through the real ADK
``Runner`` + ``InMemorySessionService`` - the same machinery the FastAPI app
uses - while the tool layer (Firestore / Gemini / Memory Bank) is mocked by the
individual test modules.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


class FleetHarness:
    """Runs one ADK agent in a fresh in-memory session."""

    APP_NAME = "vigilux-sentinel-test"
    USER_ID = "test-user"

    def __init__(self, agent):
        from google.adk.sessions import InMemorySessionService

        self.agent = agent
        self.session_service = InMemorySessionService()
        self.session = None
        self.events = []
        self.final = None

    async def create_session(self, session_id: str = "test-session"):
        self.session = await self.session_service.create_session(
            app_name=self.APP_NAME,
            user_id=self.USER_ID,
            session_id=session_id,
        )
        return self.session

    async def run(
        self,
        session_id: str = "test-session",
        message: str = "run",
        state_delta: dict | None = None,
    ):
        from google.adk import Runner
        from google.genai import types

        runner = Runner(
            app_name=self.APP_NAME,
            agent=self.agent,
            session_service=self.session_service,
        )
        self.events = []
        async for event in runner.run_async(
            user_id=self.USER_ID,
            session_id=session_id,
            new_message=types.Content(
                role="user", parts=[types.Part(text=message)]
            ),
            state_delta=state_delta,
        ):
            self.events.append(event)
        self.final = next(
            (e for e in reversed(self.events) if e.is_final_response()), None
        )
        return self.events


def final_text(final) -> str | None:
    if final is None or not final.content or not final.content.parts:
        return None
    return final.content.parts[0].text