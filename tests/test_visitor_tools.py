from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.database.models import Visitante
from app.tools.context import MissingSessionApartmentError, get_session_apartment
from app.tools.visitors import listar_meus_visitantes, solicitar_autorizacao_visitante
from tests.tool_helpers import confirmation, ctx


async def _names(factory) -> list[str]:
    async with factory() as s:
        return [v.nome for v in await s.scalars(select(Visitante))]


async def test_list_isolated(tools_wired):
    r101 = await listar_meus_visitantes(ctx("101"))
    assert r101["status"] == "success"
    assert "Marina Duarte" not in json.dumps(r101)
    r302 = await listar_meus_visitantes(ctx("302"))
    assert [v["nome"] for v in r302["visitantes"]] == ["Marina Duarte"]


async def test_request_asks_confirmation_without_writing(tools_wired):
    c = ctx("101")
    res = await solicitar_autorizacao_visitante("Joana Ribeiro", "2030-04-21", c)
    details = {"acao": "autorizar_visitante", "nome": "Joana Ribeiro", "data": "2030-04-21"}
    assert res == {"status": "pending_confirmation", **details}
    assert len(c.requests) == 1 and c.requests[0]["payload"] == details
    assert "Joana Ribeiro" not in await _names(tools_wired)


async def test_approved_authorizes_visitor(tools_wired):
    c = ctx("101", confirmation=confirmation(True))
    res = await solicitar_autorizacao_visitante("Joana Ribeiro", "2030-04-21", c)
    assert res == {"status": "authorized", "nome": "Joana Ribeiro", "data": "2030-04-21"}
    assert (await _names(tools_wired)).count("Joana Ribeiro") == 1


async def test_rejected_does_not_write(tools_wired):
    c = ctx("101", confirmation=confirmation(False))
    assert await solicitar_autorizacao_visitante("Joana Ribeiro", "2030-04-21", c) == {
        "status": "rejected"
    }
    assert "Joana Ribeiro" not in await _names(tools_wired)


async def test_invalid_inputs(tools_wired):
    assert (await solicitar_autorizacao_visitante("Joana", "21/04/2030", ctx("101")))["status"] == "invalid_input"
    assert (await solicitar_autorizacao_visitante("  ", "2030-04-21", ctx("101")))["status"] == "invalid_input"


async def test_missing_session_apartment(tools_wired):
    assert (await listar_meus_visitantes(ctx(None)))["status"] == "invalid_session"
    res = await solicitar_autorizacao_visitante("Joana", "2030-04-21", ctx(None))
    assert res["status"] == "invalid_session"
    assert "Joana" not in await _names(tools_wired)


def test_helper_has_no_default():
    with pytest.raises(MissingSessionApartmentError):
        get_session_apartment(ctx(None))
    with pytest.raises(MissingSessionApartmentError):
        get_session_apartment(object())
    assert get_session_apartment(ctx("101")) == "101"
