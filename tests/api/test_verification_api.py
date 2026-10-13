import datetime as dt

from tests.api.conftest import new_session, reservas, say, visitantes


async def test_initial_reservations_and_iso_dates(client):
    assert await reservas(client, "101") == [
        {"codigo": "RSV-1377", "area": "quadra", "data": "2030-03-09"}
    ]
    assert await reservas(client, "302") == [
        {"codigo": "RSV-4821", "area": "salao-de-festas", "data": "2030-03-16"}
    ]
    assert await reservas(client, "102") == []
    for r in await reservas(client, "201"):
        dt.date.fromisoformat(r["data"])


async def test_initial_visitors(client):
    assert await visitantes(client, "302") == [{"nome": "Marina Duarte", "data": "2030-03-16"}]
    assert await visitantes(client, "101") == []


async def test_unknown_apartment_is_404(client):
    assert (await client.get("/apartamentos/999/reservas")).status_code == 404
    assert (await client.get("/apartamentos/999/visitantes")).status_code == 404


async def test_cancelled_reservations_are_not_listed(client):
    sid = await new_session(client, "101")
    await say(client, sid, "Cancele minha reserva RSV-1377.")
    assert await reservas(client, "101") == []


async def test_verification_routes_do_not_touch_agents(client):
    before = await client.app.state.adk_runtime._sessions.list_sessions(
        app_name="residencial_aurora", user_id="morador"
    )
    await reservas(client, "101")
    await visitantes(client, "101")
    after = await client.app.state.adk_runtime._sessions.list_sessions(
        app_name="residencial_aurora", user_id="morador"
    )
    assert before.sessions == after.sessions == []
