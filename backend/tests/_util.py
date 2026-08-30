"""Shared test utilities: run a single ADK agent through the real Runner.

The harness uses the same ``Runner`` + ``InMemorySessionService`` machinery as
the FastAPI app, while individual test modules mock the tool layer
(Firestore / Gemini / Memory Bank).
"""

from __future__ import annotations

from google.adk import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

APP_NAME = "vigilux-sentinel-test"
USER_ID = "test-user"


class FleetHarness:
    """Runs one ADK agent (or the orchestrator) in a fresh in-memory session."""

    def __init__(self, agent):
        self.agent = agent
        self.session_service = InMemorySessionService()
        self.session = None
        self.events = []
        self.final = None

    async def create_session(self, session_id: str = "test-session"):
        self.session = await self.session_service.create_session(
            app_name=APP_NAME,
            user_id=USER_ID,
            session_id=session_id,
        )
        return self.session

    async def run(
        self,
        session_id: str = "test-session",
        message: str = "run",
        state_delta: dict | None = None,
    ):
        runner = Runner(
            app_name=APP_NAME,
            agent=self.agent,
            session_service=self.session_service,
        )
        self.events = []
        async for event in runner.run_async(
            user_id=USER_ID,
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