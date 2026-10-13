"""ADV-033..040: corrida pelo mesmo salão/data. Garantia final = índice único parcial no banco."""

from __future__ import annotations

import asyncio
import datetime as dt
import itertools

import httpx
import pytest

from app.services.reservation_service import ReservationService
from tests.adversarial.conftest import calls_and_responses, tool_responses
from tests.adversarial.realserver import Server, domain_rows, make_env, reset_db

PAID_0511 = "Reserve o salão de festas para 2030-05-11."
SALAO, D0511 = "salao-de-festas", "2030-05-11"
FORBIDDEN_IN_BODY = ("Traceback", "IntegrityError", "database is locked", "OperationalError", "sqlite")


# --------------------------------------------------------------------------- em processo (ASGI)
async def test_adv033_to_036_two_sessions_race_200_200_one_active_reservation(world):
    s3, s4 = await world.session("101"), await world.session("201")
    [p3] = (await world.ok(s3, PAID_0511))["confirmacoes_pendentes"]
    [p4] = (await world.ok(s4, PAID_0511))["confirmacoes_pendentes"]
    assert p3["id"] != p4["id"]
    r3, r4 = await asyncio.gather(world.answer(s3, p3["id"], True), world.answer(s4, p4["id"], True))
    assert (r3.status_code, r4.status_code) == (200, 200)
    ativas = await world.active(SALAO, D0511)
    assert len(ativas) == 1  # exatamente uma, somando 101 e 201
    outcomes = []
    for sid in (s3, s4):
        outcomes += [r["status"] for r in tool_responses(await world.events(sid), "solicitar_reserva")
                     if r["status"] in ("created", "unavailable")]
    assert sorted(outcomes) == ["created", "unavailable"]  # a perdedora é resposta funcional
    for r in (r3, r4):
        assert not any(w in r.text for w in FORBIDDEN_IN_BODY)


async def test_adv037_stress_ten_sessions_one_winner_nine_unavailable(world):
    apts = ["101", "102", "201", "202", "301", "302", "101", "102", "201", "202"]
    sessions = [await world.session(a) for a in apts]
    pend = [(await world.ok(s, PAID_0511))["confirmacoes_pendentes"][0]["id"] for s in sessions]
    assert len(set(pend)) == 10
    rs = await asyncio.gather(*(world.answer(s, c, True) for s, c in zip(sessions, pend)))
    assert [r.status_code for r in rs] == [200] * 10  # 0 HTTP 500 / 503
    assert len(await world.active(SALAO, D0511)) == 1  # 0 duplicidades
    outcomes = []
    for sid in sessions:
        outcomes += [r["status"] for r in tool_responses(await world.events(sid), "solicitar_reserva")
                     if r["status"] in ("created", "unavailable")]
    assert outcomes.count("created") == 1 and outcomes.count("unavailable") == 9
    assert not any(w in r.text for r in rs for w in FORBIDDEN_IN_BODY)


async def test_adv034_same_free_slot_booked_concurrently_via_messages(world):
    """Área gratuita: a corrida acontece na própria mensagem, sem confirmação."""
    sessions = [await world.session(a) for a in ("101", "102", "201", "202", "301", "302")]
    rs = await asyncio.gather(*(world.say(s, "Reserve a quadra para 2030-09-09.") for s in sessions))
    assert all(r.status_code == 200 for r in rs), [r.text for r in rs]
    assert len(await world.active("quadra", "2030-09-09")) == 1


# --------------------------------------------------------------------------- unicidade dos códigos
async def test_adv039_cancelled_code_is_never_reused(world):
    svc = ReservationService(world.factory)
    created = await svc.create_confirmed_reservation("101", "quadra", dt.date(2030, 7, 1))
    await svc.cancel_reservation("101", created.codigo)
    assert (await world.reserva(created.codigo)).status == "CANCELADA"
    new_codes = []
    for day in range(2, 29):
        v = await svc.create_confirmed_reservation("101", "quadra", dt.date(2030, 7, day))
        new_codes.append(v.codigo)
    assert created.codigo not in new_codes


async def test_adv039_generator_collision_with_cancelled_code_retries_with_a_new_code(world):
    svc0 = ReservationService(world.factory)
    created = await svc0.create_confirmed_reservation("101", "quadra", dt.date(2030, 7, 1))
    await svc0.cancel_reservation("101", created.codigo)
    # um gerador "azarado" tenta reutilizar o código cancelado (e um ativo) antes de achar um livre
    seq = iter([created.codigo, "RSV-1377", "RSV-NOVO0001"])
    svc = ReservationService(world.factory, code_generator=lambda: next(seq))
    v = await svc.create_confirmed_reservation("201", "quadra", dt.date(2030, 7, 2))
    assert v.codigo == "RSV-NOVO0001"
    assert (await world.reserva(created.codigo)).apartamento == "101"  # a antiga não foi tocada
    assert (await world.reserva(created.codigo)).status == "CANCELADA"


async def test_adv040_historical_code_uniqueness_including_cancelled(world):
    svc = ReservationService(world.factory)
    made = []
    for day in range(1, 31):
        made.append(await svc.create_confirmed_reservation(
            "102" if day % 2 else "201", "quadra", dt.date(2030, 8, day)))
    for v, apt in itertools.islice(zip(made, itertools.cycle(["102", "201"])), 0, 30, 3):
        owner = (await world.reserva(v.codigo)).apartamento
        await svc.cancel_reservation(owner, v.codigo)
    for day in range(1, 31):  # reutiliza as MESMAS datas liberadas pelos cancelamentos
        try:
            await svc.create_confirmed_reservation("301", "quadra", dt.date(2030, 8, day))
        except Exception:  # datas ainda ocupadas
            pass
    codigos_historicos = await world.all_codes()
    assert len(codigos_historicos) == len(set(codigos_historicos))
    assert len(codigos_historicos) > 33


# --------------------------------------------------------------------------- servidor REAL (HTTP)
def _outcomes_real(server: Server, sessions: list[str]) -> list[str]:
    out = []
    for sid in sessions:
        events = server.get(f"/sessoes/{sid}/eventos")
        out += [r["response"]["status"] for r in calls_and_responses(events)[1]
                if r.get("name") == "solicitar_reserva"
                and r["response"].get("status") in ("created", "unavailable")]
    return out


async def _gather_real(server: Server, sessions: list[str], pend: list[str]):
    async with httpx.AsyncClient(timeout=180) as c:
        return await asyncio.gather(*(
            c.post(f"{server.base}/sessoes/{s}/confirmacoes", json={"id": cid, "confirmado": True})
            for s, cid in zip(sessions, pend)))


@pytest.mark.parametrize("n", [2, 10])
def test_adv034_035_037_038_real_server_http_race(tmp_path, n):
    env = make_env(tmp_path)
    reset_db(env)
    log = tmp_path / "s.log"
    server = Server(env, log).wait_ready()
    try:
        apts = ["101", "201", "102", "202", "301", "302", "101", "201", "102", "202"][:n]
        sessions = [server.session(a) for a in apts]
        pend = [server.say(s, PAID_0511)["confirmacoes_pendentes"][0]["id"] for s in sessions]
        assert len(set(pend)) == n  # cada sessão com a sua confirmação
        rs = asyncio.run(_gather_real(server, sessions, pend))
        assert [r.status_code for r in rs] == [200] * n  # 200 + 200 (+...), nunca 500/503
        rows = domain_rows(tmp_path, "SELECT apartamento FROM reservas WHERE area=? AND data=? "
                                     "AND status='ATIVA'", (SALAO, D0511))
        assert len(rows) == 1  # exatamente 1
        # 101 + 201 somados via endpoints públicos também dão 1
        total = sum(1 for a in set(apts) for r in server.get(f"/apartamentos/{a}/reservas")
                    if r["area"] == SALAO and r["data"] == D0511)
        assert total == 1
        outcomes = _outcomes_real(server, sessions)
        assert outcomes.count("created") == 1 and outcomes.count("unavailable") == n - 1
        assert not any(w in r.text for r in rs for w in FORBIDDEN_IN_BODY)
        text = server.log_text()
        assert "database is locked" not in text, "ADV-038: lock no fluxo esperado"
        assert "Traceback" not in text
    finally:
        server.stop()
