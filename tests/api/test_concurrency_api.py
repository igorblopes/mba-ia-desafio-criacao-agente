import asyncio

from tests.api.conftest import answer, new_session, reservas, say
from tests.scripted_plan import PAID_0511


async def test_concurrent_http_approvals_leave_exactly_one_active_reservation(client):
    s3, s4 = await new_session(client, "101"), await new_session(client, "201")
    [p3] = (await say(client, s3, PAID_0511))["confirmacoes_pendentes"]
    [p4] = (await say(client, s4, PAID_0511))["confirmacoes_pendentes"]
    assert p3["id"] != p4["id"]  # cada sessão com a sua confirmação

    r3, r4 = await asyncio.gather(
        answer(client, s3, p3["id"], True), answer(client, s4, p4["id"], True)
    )
    assert (r3.status_code, r4.status_code) == (200, 200)

    ativas = [
        (apt, r)
        for apt in ("101", "201")
        for r in await reservas(client, apt)
        if r["area"] == "salao-de-festas" and r["data"] == "2030-05-11"
    ]
    assert len(ativas) == 1
    # a perdedora respondeu com resultado funcional, não com erro técnico
    for r in (r3, r4):
        assert set(r.json()) == {"resposta", "confirmacoes_pendentes"}
        assert r.json()["confirmacoes_pendentes"] == []


async def test_same_confirmation_answered_concurrently_runs_once(client):
    sid = await new_session(client)
    [p] = (await say(client, sid, PAID_0511))["confirmacoes_pendentes"]
    results = await asyncio.gather(*(answer(client, sid, p["id"], True) for _ in range(5)))
    assert sorted(r.status_code for r in results) == [200, 409, 409, 409, 409]
    assert len([r for r in await reservas(client, "101") if r["data"] == "2030-05-11"]) == 1
