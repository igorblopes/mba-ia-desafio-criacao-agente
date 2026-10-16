"""Fronteira entre a camada HTTP e o Google ADK.

A API conhece apenas ``AdkRuntime``: Runner, SessionService, ``FunctionResponse``,
``invocation_id``, retomada e parsing de eventos ficam escondidos aqui.

Divisão de responsabilidades:
* ADK (``DatabaseSessionService`` -> ``adk_sessions.db``): sessão, eventos, invocation,
  retomada e Tool Confirmation.
* Aplicação (``ConfirmationService`` -> ``condominio.db``): estado público da confirmação,
  idempotência (claim atômico), validação de sessão.

Identidade: o apartamento é gravado em ``state`` NA CRIAÇÃO da sessão e lido pelas Tools via
``ToolContext``. Nada neste módulo (nem a tabela de confirmações) é fonte de identidade.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import LlmCallsLimitExceededError
from google.adk.agents.run_config import RunConfig
from google.adk.apps import App, ResumabilityConfig
from google.adk.events import Event
from google.adk.runners import Runner
from google.adk.sessions import BaseSessionService, Session
from google.genai import types
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.concierge import build_concierge
from app.agents.regulation import build_regulation_agent
from app.agents.reservations import build_reservation_agent
from app.agents.visitors import build_visitor_agent
from app.domain.errors import AgentRunLimitError, ConfirmationResumeError, SessionNotFoundError
from app.domain.types import ConfirmationRecord, ConfirmationStatus
from app.runtime.confirmations import (
    CONFIRMATION_FUNCTION_NAME,
    PendingConfirmation,
    build_confirmation_response,
    extract_pending_confirmations,
)
from app.runtime.session_service import create_session_service
from app.services.confirmation_service import ConfirmationService

logger = logging.getLogger("aurora.confirmation")

APP_NAME = "residencial_aurora"
# A identidade do morador NÃO vem do user_id do ADK (é só chave de partição de sessões);
# vem de ``state["apartamento"]``. Um valor fixo evita criar uma segunda fonte de identidade.
RUNTIME_USER_ID = "morador"

# Teto de chamadas de LLM por execução. O padrão do ADK (500) deixa um modelo em laço (ex.: emitindo
# a função reservada ``adk_request_confirmation``, que o ADK remove do contexto e portanto repete
# para sempre) gastar ~500 chamadas e terminar em HTTP 500 (ADV-050 / F-1). Um fluxo legítimo usa
# poucas: concierge -> transferência -> especialista -> Tool -> resposta (+ encadeamentos de Tools).
MAX_LLM_CALLS_PER_RUN = 25


@dataclass(frozen=True, slots=True)
class SessionInfo:
    id: str
    apartment: str  # lido de session.state["apartamento"]
    event_count: int


@dataclass(frozen=True, slots=True)
class EventView:
    id: str
    invocation_id: str
    author: str
    kind: str  # text | tool_call | tool_response | confirmation_request | confirmation_response
    text: str = ""
    name: str = ""
    call_id: str = ""


@dataclass(frozen=True, slots=True)
class MessageResult:
    session_id: str
    reply: str
    pending_confirmations: list[ConfirmationRecord]
    event_count: int  # eventos da sessão após a execução


@dataclass(frozen=True, slots=True)
class ResumeResult:
    confirmation_id: str
    session_id: str
    invocation_id: str
    agent_name: str
    action: str
    status: ConfirmationStatus  # APPROVED | REJECTED (resposta do usuário, não o negócio)
    tool_result: dict[str, Any] | None  # retorno da Tool original (ex.: {"status": "created"})
    reply: str
    event_count: int
    new_events: list[EventView] = field(default_factory=list)


def _apartment_of(session: Session) -> str:
    value = session.state.get("apartamento")
    return str(value) if value is not None else ""


def _texts(events: Iterable[Event]) -> str:
    chunks: list[str] = []
    for ev in events:
        if ev.author == "user" or ev.partial or not ev.content:
            continue
        chunks.extend(p.text for p in ev.content.parts or [] if p.text and not p.thought)
    return "\n".join(chunks).strip()


def _view(ev: Event) -> list[EventView]:
    views: list[EventView] = []
    base = {"id": ev.id, "invocation_id": ev.invocation_id or "", "author": ev.author or ""}
    for call in ev.get_function_calls():
        kind = "confirmation_request" if call.name == CONFIRMATION_FUNCTION_NAME else "tool_call"
        views.append(EventView(kind=kind, name=call.name or "", call_id=call.id or "", **base))
    for resp in ev.get_function_responses():
        kind = (
            "confirmation_response"
            if resp.name == CONFIRMATION_FUNCTION_NAME
            else "tool_response"
        )
        views.append(EventView(kind=kind, name=resp.name or "", call_id=resp.id or "", **base))
    if ev.content and not views:
        text = "".join(p.text or "" for p in ev.content.parts or [])
        if text:
            views.append(EventView(kind="text", text=text, **base))
    return views


def _find_confirmation_call(session: Session, confirmation_id: str) -> tuple[Event, dict] | None:
    """Evento (e args) da chamada ``adk_request_confirmation`` com esse ID, na sessão."""
    for ev in session.events:
        for call in ev.get_function_calls():
            if call.name == CONFIRMATION_FUNCTION_NAME and call.id == confirmation_id:
                return ev, dict(call.args or {})
    return None


def _answered_ids(session: Session) -> set[str]:
    return {
        r.id
        for ev in session.events
        for r in ev.get_function_responses()
        if r.name == CONFIRMATION_FUNCTION_NAME and r.id
    }


class AdkRuntime:
    def __init__(
        self,
        *,
        session_service: BaseSessionService,
        confirmation_service: ConfirmationService,
        root_agent: BaseAgent,
        app_name: str = APP_NAME,
    ) -> None:
        self._sessions = session_service
        self._confirmations = confirmation_service
        self._app_name = app_name
        # Resumability: permite retomar a invocation pausada por Tool Confirmation a partir
        # dos eventos persistidos (ADK 2.9.1: apps.ResumabilityConfig(is_resumable=True)).
        self._app = App(
            name=app_name,
            root_agent=root_agent,
            resumability_config=ResumabilityConfig(is_resumable=True),
        )
        self._runner = Runner(app=self._app, session_service=session_service)

    @property
    def confirmations(self) -> ConfirmationService:
        return self._confirmations

    async def close(self) -> None:
        await self._runner.close()
        await self._sessions.close()

    # ------------------------------------------------------------------ sessões

    async def create_session(self, apartment: str, session_id: str | None = None) -> SessionInfo:
        """Cria sessão persistente com a identidade já no ``state`` (único ponto de escrita)."""
        session = await self._sessions.create_session(
            app_name=self._app_name,
            user_id=RUNTIME_USER_ID,
            session_id=session_id,
            state={"apartamento": str(apartment).strip()},
        )
        return SessionInfo(session.id, _apartment_of(session), len(session.events))

    async def _require_session(self, session_id: str) -> Session:
        session = await self._sessions.get_session(
            app_name=self._app_name, user_id=RUNTIME_USER_ID, session_id=session_id
        )
        if session is None:
            raise SessionNotFoundError()
        return session

    async def get_session(self, session_id: str) -> SessionInfo:
        session = await self._require_session(session_id)
        return SessionInfo(session.id, _apartment_of(session), len(session.events))

    async def get_events(self, session_id: str) -> list[dict[str, Any]]:
        """Eventos integrais, em ordem, um objeto JSON por evento persistido.

        Preserva conteúdo multipart, argumentos, respostas, actions e metadados.
        A projeção de diagnóstico fica em get_event_views, não no contrato público.
        """
        session = await self._require_session(session_id)
        return [ev.model_dump(mode="json") for ev in session.events]

    async def get_event_views(self, session_id: str) -> list[EventView]:
        """Resumo para diagnóstico; pode gerar várias views por evento."""
        session = await self._require_session(session_id)
        return [v for ev in session.events for v in _view(ev)]

    # ---------------------------------------------------------------- mensagens

    async def _run(self, session_id: str, message: types.Content) -> list[Event]:
        try:
            return [
                ev
                async for ev in self._runner.run_async(
                    user_id=RUNTIME_USER_ID,
                    session_id=session_id,
                    new_message=message,
                    run_config=RunConfig(max_llm_calls=MAX_LLM_CALLS_PER_RUN),
                )
            ]
        except LlmCallsLimitExceededError as exc:
            logger.error("agent_run_limit_exceeded session_id=%s limit=%d",
                         session_id, MAX_LLM_CALLS_PER_RUN)
            raise AgentRunLimitError() from exc

    async def _register_pending(self, session_id: str, events: Iterable[Event]) -> None:
        for p in extract_pending_confirmations(events):
            await self._confirmations.create_pending(
                id=p.id,
                session_id=session_id,
                invocation_id=p.invocation_id,
                agent_name=p.agent_name,
                action=p.action,
                details=p.details,
            )

    async def send_message(self, session_id: str, text: str) -> MessageResult:
        """Texto do morador. Se o ADK pedir confirmação, ela é persistida como PENDING."""
        await self._require_session(session_id)
        try:
            events = await self._run(
                session_id, types.Content(role="user", parts=[types.Part(text=text)])
            )
        except AgentRunLimitError:
            # Pedidos de confirmação REAIS já gravados pelo ADK antes do laço não podem ficar
            # sem registro: reconcilia (best-effort) antes de devolver o erro controlado.
            try:
                await self.list_pending_confirmations(session_id)
            except Exception:  # noqa: BLE001 - o erro original prevalece
                logger.exception("reconcile_after_run_limit_failed session_id=%s", session_id)
            raise
        await self._register_pending(session_id, events)
        session = await self._require_session(session_id)
        return MessageResult(
            session_id=session_id,
            reply=_texts(events),
            pending_confirmations=await self.list_pending_confirmations(session_id),
            event_count=len(session.events),
        )

    async def list_pending_confirmations(self, session_id: str) -> list[ConfirmationRecord]:
        """Pendências da sessão. Reconcilia antes: pedido já gravado pelo ADK mas ainda não
        registrado (queda entre os dois commits) é inserido como PENDING."""
        session = await self._require_session(session_id)
        answered = _answered_ids(session)
        unanswered = [
            p
            for p in extract_pending_confirmations(session.events)
            if p.id not in answered
        ]
        for p in unanswered:
            await self._confirmations.create_pending(
                id=p.id,
                session_id=session_id,
                invocation_id=p.invocation_id,
                agent_name=p.agent_name,
                action=p.action,
                details=p.details,
            )
        return await self._confirmations.list_pending_for_session(session_id)

    # ---------------------------------------------------------------- confirmação

    async def resume_confirmation(
        self, session_id: str, confirmation_id: str, confirmed: bool
    ) -> ResumeResult:
        """Responde a uma confirmação PENDING da sessão e retoma a invocation correta.

        Levanta ``ConfirmationNotPendingError`` (inexistente / outra sessão / já respondida)
        e ``ConfirmationResumeError`` (falha técnica na retomada).
        """
        session = await self._require_session(session_id)

        # Recupera pedidos persistidos pelo ADK antes de uma queda entre os commits.
        # O insert idempotente não reabre estados finais nem PROCESSING.
        await self.list_pending_confirmations(session_id)

        # 1-2. claim atômico PENDING -> PROCESSING (só uma resposta passa daqui)
        record = await self._confirmations.claim_pending(confirmation_id, session_id)
        events_before = len(session.events)

        try:
            found = _find_confirmation_call(session, record.id)
            if found is None:
                raise ValueError("confirmation call missing in session")
            call_event, call_args = found
            # 3. invocation_id REGISTRADO tem de ser o do evento que originou a chamada.
            if (call_event.invocation_id or "") != record.invocation_id:
                raise ValueError("invocation mismatch")
            original_call_id = str((call_args.get("originalFunctionCall") or {}).get("id") or "")

            # 4-5. FunctionResponse com o function_call_id; o Runner resolve a invocation
            # pelo evento da chamada (resumability ligada) e re-executa a Tool original.
            events = await self._run(session_id, build_confirmation_response(record.id, confirmed))
        except Exception as exc:
            await self._on_resume_failure(record, events_before, exc)
            raise AssertionError("unreachable")  # _on_resume_failure sempre levanta

        # 6-7. A Tool original precisa ter respondido (executou ou rejeitou).
        tool_result = next(
            (
                dict(r.response or {})
                for ev in events
                for r in ev.get_function_responses()
                if r.id == original_call_id and r.name != CONFIRMATION_FUNCTION_NAME
            ),
            None,
        )
        if tool_result is None:
            logger.error(
                "confirmation_resume_failed session_id=%s confirmation_id=%s "
                "invocation_id=%s agent_name=%s reason=no_tool_response",
                session_id, record.id, record.invocation_id, record.agent_name,
            )
            raise ConfirmationResumeError(released=False)

        # 8. APPROVED/REJECTED = resposta do usuário. O resultado de negócio vai em tool_result.
        if confirmed:
            await self._confirmations.mark_approved(record)
        else:
            await self._confirmations.mark_rejected(record)

        # Chamadas de confirmação novas feitas durante a retomada (não esperado) são persistidas.
        await self._register_pending(session_id, events)
        session = await self._require_session(session_id)
        return ResumeResult(
            confirmation_id=record.id,
            session_id=session_id,
            invocation_id=record.invocation_id,
            agent_name=record.agent_name,
            action=record.action,
            status=ConfirmationStatus.APPROVED if confirmed else ConfirmationStatus.REJECTED,
            tool_result=tool_result,
            reply=_texts(events),
            event_count=len(session.events),
            new_events=[v for ev in events for v in _view(ev)],
        )

    async def _on_resume_failure(
        self, record: ConfirmationRecord, events_before: int, exc: Exception
    ) -> None:
        """Volta a PENDING só se é certo que a Tool não executou; senão fica PROCESSING.

        Critério: o ADK acrescenta o evento do usuário (FunctionResponse) ANTES de executar a
        Tool. Se a contagem de eventos persistidos não mudou, nada executou -> libera.
        Qualquer outro caso é ambíguo; prioriza-se não duplicar o efeito.
        """
        released = False
        try:
            session = await self._require_session(record.session_id)
            if len(session.events) == events_before:
                released = await self._confirmations.release_processing(record)
        except Exception:  # noqa: BLE001 - diagnóstico best-effort; a falha original prevalece
            logger.exception("confirmation_release_check_failed confirmation_id=%s", record.id)
        logger.error(
            "confirmation_resume_failed session_id=%s confirmation_id=%s invocation_id=%s "
            "agent_name=%s released=%s error=%s",
            record.session_id, record.id, record.invocation_id, record.agent_name,
            released, type(exc).__name__,
        )
        raise ConfirmationResumeError(released=released) from exc


def build_adk_runtime(
    *,
    domain_session_factory: async_sessionmaker[AsyncSession] | None = None,
    session_db_url: str | None = None,
    llm: Any = None,
) -> AdkRuntime:
    """Monta o runtime real: ``DatabaseSessionService`` + ``ConfirmationService`` + agentes.

    ``llm`` substitui o modelo de todos os agentes (testes sem rede). Sem ele, usa o Gemini
    configurado nos próprios agentes.
    """
    from app.database.connection import get_session_factory
    from app.services.provider import configure_services

    factory = domain_session_factory or get_session_factory()
    configure_services(factory)  # Tools -> mesmo banco de domínio do ConfirmationService

    reservation, visitor = build_reservation_agent(), build_visitor_agent()
    regulation = build_regulation_agent()
    root = build_concierge(reservation=reservation, visitor=visitor, regulation=regulation)
    if llm is not None:
        for agent in (root, reservation, visitor, regulation):
            agent.model = llm
    return AdkRuntime(
        session_service=create_session_service(session_db_url),
        confirmation_service=ConfirmationService(factory),
        root_agent=root,
    )
