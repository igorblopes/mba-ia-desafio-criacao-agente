"""ADV-041..047: abuso do contrato HTTP. Nenhuma entrada ruim pode gerar efeito nem 500."""

from __future__ import annotations

import pytest

from tests.adversarial.conftest import INTERNALS

PAID = "Reserve o salão de festas para 2030-04-20."


async def _session_count(world) -> int:
    rt = world.app.state.adk_runtime
    listed = await rt._sessions.list_sessions(app_name=rt._app_name, user_id="morador")
    return len(listed.sessions)


async def _snapshot(world):
    from sqlalchemy import func, select

    from app.database.models import Confirmacao
    async with world.factory() as s:
        n_conf = await s.scalar(select(func.count()).select_from(Confirmacao))
    return (await world.count_reservas(), len(await world.visitors("101")), n_conf,
            await _session_count(world))


@pytest.mark.parametrize("method,path,body", [
    ("post", "/sessoes/INVALIDA/mensagens", {"texto": "oi"}),
    ("get", "/sessoes/INVALIDA/eventos", None),
    ("post", "/sessoes/INVALIDA/confirmacoes", {"id": "ABC", "confirmado": True}),
    ("post", "/sessoes/%2e%2e%2f%2e%2e%2fetc%2fpasswd/mensagens", {"texto": "oi"}),
    ("post", "/sessoes/" + "9" * 3000 + "/mensagens", {"texto": "oi"}),
    ("post", "/sessoes/ç😀/mensagens", {"texto": "oi"}),
    ("get", "/sessoes/%00/eventos", None),
])
async def test_adv041_nonexistent_session_is_404_and_is_not_created(world, method, path, body):
    before = await _snapshot(world)
    r = await getattr(world.client, method)(path, **({"json": body} if body is not None else {}))
    assert r.status_code == 404, (r.status_code, r.text)
    assert not any(i in r.text for i in INTERNALS)
    assert await _snapshot(world) == before  # nenhuma sessão criada automaticamente


async def test_adv042_unknown_confirmation_in_existing_session_is_409_not_404(world):
    sid = await world.session("101")
    r = await world.answer(sid, "NAO-EXISTE", True)
    assert r.status_code == 409 and r.status_code != 404


@pytest.mark.parametrize("path,body", [
    ("/sessoes", {}),
    ("/sessoes", {"apartamento": ""}),
    ("/sessoes", {"apartamento": "   "}),
    ("/sessoes", {"apartamento": None}),
    ("/sessoes", {"outro": "101"}),
    ("/sessoes", []),
    ("/sessoes", "101"),
])
async def test_adv043_adv044_create_session_rejects_bad_payloads(world, path, body):
    before = await _snapshot(world)
    r = await world.client.post(path, json=body)
    assert 400 <= r.status_code < 500, (r.status_code, r.text)
    assert await _snapshot(world) == before


@pytest.mark.parametrize("body", [
    {}, {"texto": None}, {"texto": 123}, {"texto": True}, {"texto": ["oi"]}, {"texto": {"a": 1}},
    {"txt": "oi"}, {"texto": ""}, {"texto": "   "}, {"texto": "\n\t "}, [], "oi",
])
async def test_adv043_adv044_adv046_message_validation_without_side_effects(world, body):
    sid = await world.session("101")
    events_before = await world.events(sid)
    before = await _snapshot(world)
    r = await world.client.post(f"/sessoes/{sid}/mensagens", json=body)
    assert 400 <= r.status_code < 500, (r.status_code, r.text)
    assert await world.events(sid) == events_before  # nenhuma Tool executada, nenhum evento novo
    assert await _snapshot(world) == before


@pytest.mark.parametrize("body", [
    {}, {"id": "ABC"}, {"confirmado": True}, {"id": "ABC", "confirmado": "sim"},
    {"id": "ABC", "confirmado": "true"}, {"id": "ABC", "confirmado": 1}, {"id": "ABC", "confirmado": 0},
    {"id": "ABC", "confirmado": None}, {"id": "", "confirmado": True}, {"id": 123, "confirmado": True},
    {"id": ["ABC"], "confirmado": True}, [], "ABC",
])
async def test_adv043_adv044_confirmation_payload_validation_without_side_effects(world, body):
    sid = await world.session("101")
    p = (await world.ok(sid, PAID))["confirmacoes_pendentes"][0]
    before = await _snapshot(world)
    r = await world.client.post(f"/sessoes/{sid}/confirmacoes", json=body)
    assert 400 <= r.status_code < 500 and r.status_code != 409, (r.status_code, r.text)
    assert await world.confirmation_status(p["id"]) == "PENDING"  # nada consumido
    assert await _snapshot(world) == before


@pytest.mark.parametrize("raw", [b'{"texto": "oi"', b"{", b"", b"null", b"\xff\xfe\x00", b'{"texto": "oi"}}',
                                 b"{'texto': 'oi'}", b'{"texto": NaN}'])
async def test_adv045_malformed_json_is_4xx_without_state_change(world, raw):
    sid = await world.session("101")
    events_before = await world.events(sid)
    before = await _snapshot(world)
    for path in (f"/sessoes/{sid}/mensagens", f"/sessoes/{sid}/confirmacoes", "/sessoes"):
        r = await world.client.post(path, content=raw, headers={"content-type": "application/json"})
        assert 400 <= r.status_code < 500, (path, r.status_code, r.text)
        assert not any(i in r.text for i in ("Traceback", "sqlite"))
    assert await world.events(sid) == events_before
    assert await _snapshot(world) == before


async def test_adv045_wrong_content_type_and_methods(world):
    sid = await world.session("101")
    r = await world.client.post(f"/sessoes/{sid}/mensagens", content='{"texto":"oi"}',
                                headers={"content-type": "text/plain"})
    assert 400 <= r.status_code < 500
    assert (await world.client.get(f"/sessoes/{sid}/mensagens")).status_code == 405
    assert (await world.client.delete(f"/sessoes/{sid}")).status_code in (404, 405)
    assert (await world.client.put("/sessoes", json={"apartamento": "101"})).status_code == 405


@pytest.mark.parametrize("texto", ["   ", "", "\n\t "])
async def test_adv046_blank_text_never_runs_a_mutating_tool(world, texto):
    sid = await world.session("101")
    before = await _snapshot(world)
    r = await world.client.post(f"/sessoes/{sid}/mensagens", json={"texto": texto})
    assert r.status_code == 422  # contrato: texto em branco é rejeitado
    assert await _snapshot(world) == before  # sem reserva/visitante/confirmação/sessão


@pytest.mark.parametrize("texto", ["\u200b", "\x00", "\u00a0\u2003"])
async def test_adv046_invisible_characters_never_mutate_the_domain(world, texto):
    """Invisíveis passam pelo contrato, mas reserva/visitante nunca são gravados sem confirmação
    formal (a reserva paga apenas fica PENDING)."""
    sid = await world.session("101")
    before = await _snapshot(world)
    r = await world.client.post(f"/sessoes/{sid}/mensagens", json={"texto": texto})
    assert r.status_code < 500, r.status_code
    assert (await _snapshot(world))[:2] == before[:2]  # reservas e visitantes intactos


async def test_adv047_confirmation_without_any_pending_is_409_and_inert(world):
    sid = await world.session("201")
    before = await _snapshot(world)
    for fake in ("adk-inventado", "RSV-1377", "x"):
        assert (await world.answer(sid, fake, True)).status_code == 409
        assert (await world.answer(sid, fake, False)).status_code == 409
    assert await _snapshot(world) == before


@pytest.mark.parametrize("apt", ["9999", "0101", "١٠١", "101 ; DROP TABLE reservas;--", "1" * 5000,
                                 "101\x00", "%", "' OR ''='", "10 1"])
async def test_unknown_or_hostile_apartment_numbers_are_rejected_without_500(world, apt):
    before = await _snapshot(world)
    r = await world.client.post("/sessoes", json={"apartamento": apt})
    assert r.status_code in (404, 422), (r.status_code, r.text[:200])
    assert not any(i in r.text for i in INTERNALS)
    assert await _snapshot(world) == before
    from urllib.parse import quote
    g = await world.client.get(f"/apartamentos/{quote(apt, safe='')}/reservas")
    assert g.status_code in (404, 422) and g.status_code < 500
    assert await world.count_reservas() == 3  # as 3 reservas originais, intactas


async def test_whitespace_around_valid_apartment_still_binds_the_same_identity(world):
    r = await world.client.post("/sessoes", json={"apartamento": " 101 "})
    assert r.status_code == 201
    info = await world.app.state.adk_runtime.get_session(r.json()["session_id"])
    assert info.apartment == "101"


async def test_very_large_message_does_not_crash_or_mutate(world):
    sid = await world.session("101")
    before = await _snapshot(world)
    r = await world.client.post(f"/sessoes/{sid}/mensagens", json={"texto": "regulamento " * 20000})
    assert r.status_code < 500, r.status_code
    assert (await _snapshot(world))[:3] == before[:3]


@pytest.mark.parametrize("date", ["2030-02-30", "0000-00-00", "2030-13-01", "31/12/2030", "amanhã",
                                  "2030-04-20T10:00", "２０３０-０４-２０", "2030-4-2", "99999-01-01"])
async def test_invalid_dates_fail_cleanly_without_writing(world, date):
    sid = await world.session("101")
    before = await world.count_reservas()
    r = await world.say(sid, "CALL@reservation_agent solicitar_reserva "
                             '{"area_id":"quadra","data":"%s"}' % date)
    assert r.status_code == 200, r.text
    assert await world.count_reservas() == before
