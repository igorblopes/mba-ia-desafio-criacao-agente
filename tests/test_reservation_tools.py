from __future__ import annotations

import json

from sqlalchemy import select

from app.database.models import STATUS_ATIVA, Reserva
from app.tools.reservations import (
    cancelar_minha_reserva,
    listar_minhas_reservas,
    solicitar_reserva,
    verificar_disponibilidade,
)
from tests.tool_helpers import confirmation, ctx


async def _reservas(factory) -> list[Reserva]:
    async with factory() as s:
        return list(await s.scalars(select(Reserva).order_by(Reserva.codigo)))


async def test_list_uses_session_apartment(tools_wired):
    r101 = await listar_minhas_reservas(ctx("101"))
    codes = {x["codigo"] for x in r101["reservas"]}
    assert r101["status"] == "success"
    assert "RSV-1377" in codes and "RSV-4821" not in codes
    assert r101["reservas"][0] == {"codigo": "RSV-1377", "area": "quadra", "data": "2030-03-09"}
    r302 = await listar_minhas_reservas(ctx("302"))
    assert {x["codigo"] for x in r302["reservas"]} == {"RSV-4821"}


async def test_cancel_foreign_reservation_is_neutral(tools_wired):
    res = await cancelar_minha_reserva("RSV-4821", ctx("101"))
    assert res == {"status": "not_found"}
    blob = json.dumps(res)
    assert "302" not in blob and "Rafael" not in blob and "RSV-4821" not in blob
    rows = {r.codigo: r for r in await _reservas(tools_wired)}
    assert rows["RSV-4821"].status == STATUS_ATIVA and rows["RSV-4821"].apartamento == "302"


async def test_cancel_unknown_same_as_foreign(tools_wired):
    assert await cancelar_minha_reserva("RSV-0000", ctx("101")) == {"status": "not_found"}


async def test_cancel_own(tools_wired):
    res = await cancelar_minha_reserva("RSV-1377", ctx("101"))
    assert res["status"] == "cancelled" and res["codigo"] == "RSV-1377"
    assert (await listar_minhas_reservas(ctx("101")))["reservas"] == []


async def test_availability_does_not_leak_owner(tools_wired):
    res = await verificar_disponibilidade("salao-de-festas", "2030-03-16", ctx("101"))
    assert res == {"status": "success", "disponivel": False}
    blob = json.dumps(res)
    for leaked in ("302", "RSV-4821", "Rafael", "Moreira"):
        assert leaked not in blob
    free = await verificar_disponibilidade("salao-de-festas", "2030-06-01", ctx("101"))
    assert free == {"status": "success", "disponivel": True}


async def test_free_area_creates_reservation_for_session_apartment(tools_wired):
    res = await solicitar_reserva("quadra", "2030-05-02", ctx("101"))
    assert res["status"] == "created"
    assert res["area"] == "quadra" and res["data"] == "2030-05-02"
    row = next(r for r in await _reservas(tools_wired) if r.codigo == res["codigo"])
    assert row.apartamento == "101" and row.status == STATUS_ATIVA
    # mesmo pedido a partir de outro apartamento cria para o outro, não para o 101
    res2 = await solicitar_reserva("quadra", "2030-05-03", ctx("201"))
    row2 = next(r for r in await _reservas(tools_wired) if r.codigo == res2["codigo"])
    assert row2.apartamento == "201"


async def test_paid_area_requests_confirmation_and_does_not_write(tools_wired):
    before = await _reservas(tools_wired)
    c = ctx("101")
    res = await solicitar_reserva("salao-de-festas", "2030-05-01", c)
    details = {
        "acao": "reservar_area",
        "area": "salao-de-festas",
        "data": "2030-05-01",
        "taxa_centavos": 15000,
    }
    assert res == {"status": "pending_confirmation", **details}
    assert len(c.requests) == 1 and c.requests[0]["payload"] == details
    after = await _reservas(tools_wired)
    assert [r.codigo for r in after] == [r.codigo for r in before]


async def test_paid_area_approved_creates_exactly_one(tools_wired):
    details = {"acao": "reservar_area", "area": "salao-de-festas",
               "data": "2030-05-01", "taxa_centavos": 15000}
    c = ctx("101", confirmation=confirmation(True, details))
    res = await solicitar_reserva("salao-de-festas", "2030-05-01", c)
    assert res["status"] == "created" and res["area"] == "salao-de-festas"
    assert c.requests == []
    rows = [r for r in await _reservas(tools_wired) if r.data.isoformat() == "2030-05-01"]
    assert len(rows) == 1 and rows[0].apartamento == "101"


async def test_paid_area_rejected_writes_nothing(tools_wired):
    before = await _reservas(tools_wired)
    c = ctx("101", confirmation=confirmation(False, {"taxa_centavos": 15000}))
    assert await solicitar_reserva("salao-de-festas", "2030-05-01", c) == {"status": "rejected"}
    assert len(await _reservas(tools_wired)) == len(before)


async def test_free_area_never_requests_confirmation(tools_wired):
    c = ctx("101")
    assert (await solicitar_reserva("quadra", "2030-05-02", c))["status"] == "created"
    assert c.requests == []


async def test_cancel_never_requests_confirmation(tools_wired):
    c = ctx("101")
    assert (await cancelar_minha_reserva("RSV-1377", c))["status"] == "cancelled"
    assert c.requests == []


async def test_unavailable_does_not_leak(tools_wired):
    res = await solicitar_reserva("salao-de-festas", "2030-03-16", ctx("101"))
    assert res["status"] == "unavailable"
    blob = json.dumps(res)
    assert "302" not in blob and "RSV-4821" not in blob


async def test_invalid_date_and_area(tools_wired):
    for bad in ("amanhã", "2030-13-40", "2030-5-1", "", None):
        res = await solicitar_reserva("quadra", bad, ctx("101"))
        assert res["status"] == "invalid_input"
        assert "Traceback" not in json.dumps(res)
    assert (await solicitar_reserva("piscina", "2030-05-02", ctx("101")))["status"] == "area_not_found"


async def test_missing_session_apartment_is_safe(tools_wired):
    before = await _reservas(tools_wired)
    empty = ctx(None)
    assert (await listar_minhas_reservas(empty))["status"] == "invalid_session"
    assert (await solicitar_reserva("quadra", "2030-05-02", empty))["status"] == "invalid_session"
    assert (await cancelar_minha_reserva("RSV-1377", empty))["status"] == "invalid_session"
    assert (await verificar_disponibilidade("quadra", "2030-05-02", empty))["status"] == "invalid_session"
    for blank in ("", "   ", None):
        assert (await listar_minhas_reservas(ctx(blank if blank is not None else None)))["status"] == "invalid_session"
    assert [r.codigo for r in await _reservas(tools_wired)] == [r.codigo for r in before]


async def test_function_tool_run_async_injects_context(tools_wired):
    """Via FunctionTool do ADK: o modelo passa só args; tool_context é injetado."""
    from app.tools.reservations import listar_minhas_reservas_tool, solicitar_reserva_tool

    res = await listar_minhas_reservas_tool.run_async(args={}, tool_context=ctx("101"))
    assert {r["codigo"] for r in res["reservas"]} == {"RSV-1377"}
    res = await solicitar_reserva_tool.run_async(
        args={"area_id": "quadra", "data": "2030-05-02"}, tool_context=ctx("201")
    )
    assert res["status"] == "created"
