"""Runner real do ADK para exercitar Tool Confirmation (LLM roteirizado ou Gemini)."""

from __future__ import annotations

from google.adk.events import Event
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app.agents.concierge import build_concierge
from app.agents.reservations import build_reservation_agent
from app.agents.visitors import build_visitor_agent
from app.runtime.confirmations import (
    PendingConfirmation,
    build_confirmation_response,
    extract_pending_confirmations,
)

APP = "aurora_confirmation"
USER = "u"


class Harness:
    """Sessão InMemory + Runner. Passo 7 não valida DatabaseSessionService."""

    def __init__(self, llm=None, apartamento: str = "101") -> None:
        self.apartamento = apartamento
        reservation, visitor = build_reservation_agent(), build_visitor_agent()
        self.root = build_concierge(reservation=reservation, visitor=visitor)
        if llm is not None:
            for agent in (self.root, reservation, visitor):
                agent.model = llm
        self.service = InMemorySessionService()
        self.runner = Runner(agent=self.root, app_name=APP, session_service=self.service)
        self.session_id: str | None = None
        self.all_events: list[Event] = []

    async def start(self) -> "Harness":
        session = await self.service.create_session(
            app_name=APP, user_id=USER, state={"apartamento": self.apartamento}
        )
        self.session_id = session.id
        return self

    async def _run(self, message: types.Content) -> list[Event]:
        events = [
            ev
            async for ev in self.runner.run_async(
                user_id=USER, session_id=self.session_id, new_message=message
            )
        ]
        self.all_events.extend(events)
        return events

    async def send(self, text: str) -> list[Event]:
        return await self._run(types.Content(role="user", parts=[types.Part(text=text)]))

    async def respond(self, confirmation_id: str, confirmed: bool) -> list[Event]:
        return await self._run(build_confirmation_response(confirmation_id, confirmed))


def pending(events: list[Event]) -> list[PendingConfirmation]:
    return extract_pending_confirmations(events)


def tool_responses(events: list[Event]) -> list[dict]:
    return [r.response for e in events for r in e.get_function_responses()]
