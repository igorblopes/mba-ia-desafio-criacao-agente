from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from app.database.models import Visitante
from app.domain.errors import ApartmentNotFoundError, InvalidVisitorNameError
from app.domain.types import RequestStatus
from app.services.visitor_service import VisitorService


@pytest.fixture
def service(session_factory):
    return VisitorService(session_factory)


async def _names(factory) -> list[str]:
    async with factory() as s:
        return [v.nome for v in await s.scalars(select(Visitante))]


async def test_list_visitors_302(service):
    assert "Marina Duarte" in [v.nome for v in await service.list_visitors("302")]


async def test_list_visitors_isolation(service):
    assert "Marina Duarte" not in [v.nome for v in await service.list_visitors("101")]


async def test_unknown_apartment(service):
    with pytest.raises(ApartmentNotFoundError):
        await service.list_visitors("999")
    with pytest.raises(ApartmentNotFoundError):
        await service.request_authorization("999", "X", dt.date(2030, 4, 21))


async def test_request_requires_confirmation_and_does_not_write(service, session_factory):
    res = await service.request_authorization("101", "Joana Ribeiro", dt.date(2030, 4, 21))
    assert res.status is RequestStatus.REQUIRES_CONFIRMATION
    assert res.visitor_name == "Joana Ribeiro"
    assert "Joana Ribeiro" not in await _names(session_factory)


async def test_confirmed_authorization_writes(service, session_factory):
    await service.create_confirmed_authorization("101", "Joana Ribeiro", dt.date(2030, 4, 21))
    assert "Joana Ribeiro" in await _names(session_factory)
    assert "Joana Ribeiro" in [v.nome for v in await service.list_visitors("101")]
    assert "Joana Ribeiro" not in [v.nome for v in await service.list_visitors("302")]


async def test_blank_name_rejected(service, session_factory):
    before = await _names(session_factory)
    with pytest.raises(InvalidVisitorNameError):
        await service.request_authorization("101", "   ", dt.date(2030, 4, 21))
    with pytest.raises(InvalidVisitorNameError):
        await service.create_confirmed_authorization("101", "", dt.date(2030, 4, 21))
    assert await _names(session_factory) == before
