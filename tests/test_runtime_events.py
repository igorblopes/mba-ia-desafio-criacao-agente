"""Contrato integral dos eventos, incluindo eventos mistos e sem conteúdo."""
import json
import pytest
from google.adk.events import Event, EventActions
from google.genai import types
from app.runtime.adk_runtime import APP_NAME, RUNTIME_USER_ID
from app.domain.errors import SessionNotFoundError


async def test_get_events_preserves_all_parts_and_metadata(adk_runtime):
    info = await adk_runtime.create_session("101")
    session = await adk_runtime._require_session(info.id)
    # Timestamps explícitos e crescentes: o armazenamento ordena por timestamp, e no Windows o relógio
    # pode dar o MESMO valor a dois eventos criados em sequência. Nesse caso o ADK
    # desempata por ID, não pela ordem de construção.
    events = [
        Event(author="reservation_agent", invocation_id="mixed", timestamp=1_000.0, content=types.Content(
            role="model", parts=[
                types.Part(text="Texto junto da chamada."),
                types.Part(function_call=types.FunctionCall(id="call-a", name="example", args={"data": "2030-04-20"})),
                types.Part(function_response=types.FunctionResponse(id="call-b", name="other", response={"status": "success", "nested": [1, 2]})),
            ])),
        Event(author="reservation_agent", invocation_id="state-only", timestamp=1_001.0,
              actions=EventActions(state_delta={"audit_marker": "preserved"})),
    ]
    for event in events:
        await adk_runtime._sessions.append_event(session=session, event=event)
    stored = await adk_runtime._sessions.get_session(app_name=APP_NAME, user_id=RUNTIME_USER_ID, session_id=info.id)
    exported = await adk_runtime.get_events(info.id)
    assert exported == [e.model_dump(mode="json") for e in stored.events]
    assert len(exported) == (await adk_runtime.get_session(info.id)).event_count == 2
    assert len(exported[0]["content"]["parts"]) == 3
    assert exported[1]["actions"]["state_delta"] == {"audit_marker": "preserved"}
    assert json.loads(json.dumps(exported)) == exported
    exported[0]["content"]["parts"][1]["function_call"]["args"]["data"] = "changed"
    assert (await adk_runtime.get_events(info.id))[0] != exported[0]


async def test_get_events_unknown_session(adk_runtime):
    with pytest.raises(SessionNotFoundError):
        await adk_runtime.get_events("missing")


async def test_equal_timestamps_have_stable_id_order(adk_runtime):
    info = await adk_runtime.create_session("101")
    session = await adk_runtime._require_session(info.id)
    for identifier in ("event-z", "event-a"):
        await adk_runtime._sessions.append_event(session=session, event=Event(
            id=identifier, timestamp=2_000.0, author="reservation_agent",
            invocation_id=identifier, content=types.Content(
                role="model", parts=[types.Part(text=identifier)])))
    first = await adk_runtime.get_events(info.id)
    assert [event["id"] for event in first] == ["event-a", "event-z"]
    assert await adk_runtime.get_events(info.id) == first
