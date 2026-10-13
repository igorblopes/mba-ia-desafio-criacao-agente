import json

from tests.api.conftest import answer, calls_and_responses, new_session, say
from tests.regulation_support import chapters, regulation_text
from tests.scripted_plan import PAID, POOL


async def _events(client, sid):
    r = await client.get(f"/sessoes/{sid}/eventos")
    assert r.status_code == 200
    return r.json()


async def test_unknown_session_is_404_not_empty_list(client):
    r = await client.get("/sessoes/inexistente/eventos")
    assert r.status_code == 404


async def test_new_session_has_empty_event_list(client):
    sid = await new_session(client)
    assert await _events(client, sid) == []


async def test_events_expose_tool_calls_responses_and_transfer(client):
    sid = await new_session(client)
    [p] = (await say(client, sid, PAID))["confirmacoes_pendentes"]
    events = await _events(client, sid)
    assert all({"id", "author", "invocation_id", "content"} <= set(e) for e in events)
    assert events[0]["author"] == "user"
    calls, _ = calls_and_responses(events)
    names = [c["name"] for c in calls]
    assert "transfer_to_agent" in names and "solicitar_reserva" in names
    request = [c for c in calls if c["name"] == "adk_request_confirmation"]
    assert [c["id"] for c in request] == [p["id"]]
    assert any(e["author"] == "reservation_agent" for e in events)

    await answer(client, sid, p["id"], True)
    events = await _events(client, sid)
    calls, responses = calls_and_responses(events)
    by_name = {r["name"]: r for r in responses}
    assert by_name["adk_request_confirmation"]["id"] == p["id"]
    assert by_name["adk_request_confirmation"]["response"] == {"confirmed": True}
    assert by_name["solicitar_reserva"]["response"]["status"] == "created"
    assert "transfer_to_agent" in by_name
    json.dumps(events)  # JSON puro


async def test_events_are_stable_and_ordered(client):
    sid = await new_session(client)
    await say(client, sid, "Mostre minhas reservas.")
    first = await _events(client, sid)
    assert first == await _events(client, sid)
    await say(client, sid, "Mostre minhas reservas.")
    second = await _events(client, sid)
    assert second[: len(first)] == first and len(second) > len(first)


async def test_regulation_events_hold_only_retrieved_excerpts(client):
    sid = await new_session(client)
    await say(client, sid, POOL)
    events = await _events(client, sid)
    calls, responses = calls_and_responses(events)
    transfers = [c for c in calls if c["name"] == "transfer_to_agent"]
    assert [t["args"]["agent_name"] for t in transfers] == ["regulation_agent"]
    assert [c["name"] for c in calls if c["name"] == "consultar_regulamento"]
    [tool] = [r for r in responses if r["name"] == "consultar_regulamento"]
    trechos = tool["response"]["trechos"]
    assert trechos and len(trechos) < 10
    full = regulation_text()
    assert all(t["conteudo"].strip() in full for t in trechos)  # texto real, sem invenção

    blob = json.dumps(events, ensure_ascii=False)
    assert full not in blob
    relevant = {t["secao"].split(" > ")[0] for t in trechos}
    for title, body in chapters().items():
        if title not in relevant:
            assert body[:120] not in blob, f"capítulo irrelevante vazou: {title}"
