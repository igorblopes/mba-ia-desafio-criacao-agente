"""Detecção e resposta de Tool Confirmation do ADK (sem persistência; Passo 8).

Fluxo: a Tool chama ``tool_context.request_confirmation``; o ADK emite um evento com a
function call ``adk_request_confirmation``; o cliente responde com um ``FunctionResponse``
de mesmo ``id``; o ADK injeta ``tool_context.tool_confirmation`` e re-executa a Tool.

Onde estão os dados (ADK 2.9.1):
* ``id``            -> ``function_call.id`` da chamada ``adk_request_confirmation``
* ``invocation_id`` -> ``event.invocation_id``
* ``agent_name``    -> ``event.author`` (agente dono da Tool, ex.: ``reservation_agent``)
* ``payload/hint``  -> ``args["toolConfirmation"]``; chamada original -> ``args["originalFunctionCall"]``
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from google.adk.events import Event
from google.adk.flows.llm_flows.functions import REQUEST_CONFIRMATION_FUNCTION_CALL_NAME
from google.genai import types

CONFIRMATION_FUNCTION_NAME = REQUEST_CONFIRMATION_FUNCTION_CALL_NAME  # "adk_request_confirmation"


@dataclass(frozen=True, slots=True)
class PendingConfirmation:
    id: str  # function_call_id da chamada adk_request_confirmation
    invocation_id: str
    agent_name: str
    action: str
    details: dict[str, Any] = field(default_factory=dict)
    hint: str = ""
    tool_name: str = ""  # Tool original que pediu a confirmação
    original_function_call_id: str = ""


def extract_pending_confirmations(events: Iterable[Event]) -> list[PendingConfirmation]:
    """Converte eventos ADK em ``PendingConfirmation`` (ignora chamadas malformadas)."""
    found: list[PendingConfirmation] = []
    for event in events:
        for call in event.get_function_calls():
            if call.name != CONFIRMATION_FUNCTION_NAME or not call.id:
                continue
            args = call.args or {}
            confirmation = args.get("toolConfirmation") or {}
            original = args.get("originalFunctionCall") or {}
            payload = confirmation.get("payload")
            details = dict(payload) if isinstance(payload, dict) else {}
            action = str(details.pop("acao", ""))
            found.append(
                PendingConfirmation(
                    id=call.id,
                    invocation_id=event.invocation_id or "",
                    agent_name=event.author or "",
                    action=action,
                    details=details,
                    hint=str(confirmation.get("hint") or ""),
                    tool_name=str(original.get("name") or ""),
                    original_function_call_id=str(original.get("id") or ""),
                )
            )
    return found


def build_confirmation_response(confirmation_id: str, confirmed: bool) -> types.Content:
    """Mensagem formal (``FunctionResponse``) que aprova/rejeita a confirmação pendente."""
    return types.Content(
        role="user",
        parts=[
            types.Part(
                function_response=types.FunctionResponse(
                    id=confirmation_id,
                    name=CONFIRMATION_FUNCTION_NAME,
                    response={"confirmed": bool(confirmed)},
                )
            )
        ],
    )
