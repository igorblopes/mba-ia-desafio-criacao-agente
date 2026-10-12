"""Parser offline (sem Gemini, sem Runner): evento ADK -> PendingConfirmation."""

from __future__ import annotations

from google.adk.events import Event
from google.adk.tools.tool_confirmation import ToolConfirmation
from google.genai import types

from app.runtime.confirmations import (
    CONFIRMATION_FUNCTION_NAME,
    build_confirmation_response,
    extract_pending_confirmations,
)


def _confirmation_event(*, author="reservation_agent", invocation_id="inv-1", call_id="adk-conf-1",
                        payload=None, name=CONFIRMATION_FUNCTION_NAME) -> Event:
    payload = payload if payload is not None else {
        "acao": "reservar_area", "area": "salao-de-festas",
        "data": "2030-04-20", "taxa_centavos": 10000,
    }
    call = types.FunctionCall(
        name=name, id=call_id,
        args={
            "originalFunctionCall": {"name": "solicitar_reserva", "id": "adk-orig-1",
                                      "args": {"area_id": "salao-de-festas", "data": "2030-04-20"}},
            "toolConfirmation": {"hint": "Esta reserva possui cobrança.", "confirmed": False,
                                  "payload": payload},
        },
    )
    return Event(invocation_id=invocation_id, author=author,
                 content=types.Content(role="model", parts=[types.Part(function_call=call)]))


def test_event_with_confirmation_becomes_pending_confirmation():
    [p] = extract_pending_confirmations([_confirmation_event()])
    assert p.id == "adk-conf-1"
    assert p.invocation_id == "inv-1"
    assert p.agent_name == "reservation_agent"
    assert p.action == "reservar_area"
    assert p.details == {"area": "salao-de-festas", "data": "2030-04-20", "taxa_centavos": 10000}
    assert p.tool_name == "solicitar_reserva" and p.original_function_call_id == "adk-orig-1"
    assert p.hint


def test_visitor_confirmation_keeps_originating_agent():
    ev = _confirmation_event(
        author="visitor_agent", call_id="adk-conf-2",
        payload={"acao": "autorizar_visitante", "nome": "Joana Ribeiro", "data": "2030-04-21"})
    [p] = extract_pending_confirmations([ev])
    assert p.agent_name == "visitor_agent" and p.action == "autorizar_visitante"
    assert p.details == {"nome": "Joana Ribeiro", "data": "2030-04-21"}


def test_other_events_and_function_calls_are_ignored():
    plain = Event(invocation_id="i", author="reservation_agent",
                  content=types.Content(role="model", parts=[types.Part(text="oi")]))
    other = Event(invocation_id="i", author="reservation_agent",
                  content=types.Content(role="model", parts=[types.Part(
                      function_call=types.FunctionCall(name="solicitar_reserva", id="x", args={}))]))
    assert extract_pending_confirmations([plain, other]) == []


def test_malformed_confirmation_does_not_crash():
    call = types.FunctionCall(name=CONFIRMATION_FUNCTION_NAME, id="adk-bad", args={})
    ev = Event(invocation_id="i", author="a",
               content=types.Content(role="model", parts=[types.Part(function_call=call)]))
    [p] = extract_pending_confirmations([ev])
    assert p.id == "adk-bad" and p.action == "" and p.details == {}


def test_multiple_confirmations_preserve_order():
    evs = [_confirmation_event(call_id="a"), _confirmation_event(call_id="b")]
    assert [p.id for p in extract_pending_confirmations(evs)] == ["a", "b"]


def test_response_builder_uses_real_adk_types_and_ids():
    for flag in (True, False):
        content = build_confirmation_response("adk-conf-1", flag)
        assert content.role == "user"
        [part] = content.parts
        fr = part.function_response
        assert isinstance(fr, types.FunctionResponse)
        assert fr.id == "adk-conf-1" and fr.name == "adk_request_confirmation"
        assert fr.response == {"confirmed": flag}
        # o ADK consegue interpretar a resposta como ToolConfirmation
        assert ToolConfirmation.from_response_dict(fr.response).confirmed is flag
