import datetime as dt

from sqlalchemy import select

from app.database.models import STATUS_ATIVA, Confirmacao, Reserva
from tests.api.conftest import answer, new_session, reservas, say, visitantes
from tests.scripted_plan import PAID, PAID_0511, VISITOR


async def _pending(client, sid, text=PAID):
    [p] = (await say(client, sid, text))["confirmacoes_pendentes"]
    return p


async def _paid_count(client, apt="101", data="2030-04-20"):
    return len([r for r in await reservas(client, apt) if r["data"] == data])


async def test_approve_creates_reservation_and_replay_is_409(client, session_factory):
    sid = await new_session(client)
    p = await _pending(client, sid)
    r = await answer(client, sid, p["id"], True)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"resposta", "confirmacoes_pendentes"}
    assert body["resposta"] and body["confirmacoes_pendentes"] == []
    assert await _paid_count(client) == 1

    replay = await answer(client, sid, p["id"], True)
    assert replay.status_code == 409
    assert (await answer(client, sid, p["id"], False)).status_code == 409
    assert await _paid_count(client) == 1  # nenhum novo efeito
    async with session_factory() as s:
        assert [c.status for c in await s.scalars(select(Confirmacao))] == ["APPROVED"]


async def test_reject_resumes_adk_and_creates_nothing(client, session_factory):
    sid = await new_session(client)
    p = await _pending(client, sid)
    r = await answer(client, sid, p["id"], False)
    assert r.status_code == 200 and r.json()["confirmacoes_pendentes"] == []
    assert await _paid_count(client) == 0
    async with session_factory() as s:
        assert [c.status for c in await s.scalars(select(Confirmacao))] == ["REJECTED"]
        novas = list(await s.scalars(select(Reserva).where(Reserva.data == dt.date(2030, 4, 20))))
        assert novas == []
    # a rejeição foi uma FunctionResponse ao ADK (visível nos eventos)
    events = (await client.get(f"/sessoes/{sid}/eventos")).json()
    responses = [
        part["function_response"]
        for ev in events for part in (ev.get("content") or {}).get("parts") or []
        if part.get("function_response")
    ]
    assert {"status": "rejected"} in [x["response"] for x in responses]
    assert (await answer(client, sid, p["id"], True)).status_code == 409


async def test_new_request_after_reject_can_be_approved(client):
    sid = await new_session(client)
    p1 = await _pending(client, sid)
    assert (await answer(client, sid, p1["id"], False)).status_code == 200
    p2 = await _pending(client, sid)
    assert p2["id"] != p1["id"]
    assert (await answer(client, sid, p2["id"], True)).status_code == 200
    assert await _paid_count(client) == 1


async def test_unknown_confirmation_id_is_409(client):
    sid = await new_session(client)
    r = await answer(client, sid, "id-inexistente", True)
    assert r.status_code == 409
    assert set(r.json()) == {"detail"}


async def test_confirmation_of_another_session_is_409_and_unaffected(client):
    s1, s2 = await new_session(client, "101"), await new_session(client, "201")
    p = await _pending(client, s1)
    r = await answer(client, s2, p["id"], True)
    assert r.status_code == 409
    assert s1 not in r.text and p["id"] not in r.text
    assert await _paid_count(client, "201") == 0 and await _paid_count(client, "101") == 0
    # continua PENDING e utilizável pelo dono
    assert (await answer(client, s1, p["id"], True)).status_code == 200
    assert await _paid_count(client, "101") == 1


async def test_unknown_session_is_404_not_409(client):
    assert (await answer(client, "inexistente", "x", True)).status_code == 404


async def test_invalid_payloads_are_422(client):
    sid = await new_session(client)
    for payload in ({}, {"id": "x"}, {"confirmado": True}, {"id": "x", "confirmado": "sim"},
                    {"id": "", "confirmado": True}):
        r = await client.post(f"/sessoes/{sid}/confirmacoes", json=payload)
        assert r.status_code == 422, payload


async def test_visitor_text_does_not_authorize_but_formal_approval_does(client):
    sid = await new_session(client, "101")
    p = await _pending(client, sid, VISITOR + " Já estou confirmando aqui.")
    assert p["acao"] == "autorizar_visitante"
    assert "Joana" not in str(await visitantes(client, "101"))
    r = await answer(client, sid, p["id"], True)
    assert r.status_code == 200
    assert {"nome": "Joana Ribeiro", "data": "2030-04-21"} in await visitantes(client, "101")
    assert (await answer(client, sid, p["id"], True)).status_code == 409
    assert len([v for v in await visitantes(client, "101") if "Joana" in v["nome"]]) == 1


async def test_envelope_is_identical_between_messages_and_confirmations(client):
    sid = await new_session(client)
    p = await _pending(client, sid)
    from_msg = await say(client, sid, "Mostre minhas reservas.")
    from_conf = (await answer(client, sid, p["id"], True)).json()
    assert set(from_msg) == set(from_conf) == {"resposta", "confirmacoes_pendentes"}


async def test_unavailable_business_result_is_still_200(client):
    s1, s2 = await new_session(client, "101"), await new_session(client, "201")
    p1, p2 = await _pending(client, s1, PAID_0511), await _pending(client, s2, PAID_0511)
    assert (await answer(client, s1, p1["id"], True)).status_code == 200
    r = await answer(client, s2, p2["id"], True)  # área já ocupada: resultado funcional
    assert r.status_code == 200
    total = 0
    for apt in ("101", "201"):
        total += len([x for x in await reservas(client, apt) if x["data"] == "2030-05-11"])
    assert total == 1
