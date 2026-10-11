"""Regressões de classificação e contenção, sempre em SQLite temporário."""

import datetime as dt
import json
import sqlite3

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError

from app.database.models import Reserva, Visitante
from app.domain.errors import AreaUnavailableError, DomainError, StorageBusyError
from app.repositories.reservation_repository import ReservationRepository
from app.services.reservation_service import ReservationService
from app.services.visitor_service import VisitorService
from app.tools import reservations, visitors
from tests.tool_helpers import ctx

DAY = dt.date(2035, 1, 1)


@pytest.mark.parametrize("existing", ["slot", "code"])
async def test_check_violation_is_not_misclassified(session_factory, monkeypatch, existing):
    svc = ReservationService(session_factory)
    winner = await svc.create_confirmed_reservation("101", "quadra", DAY)
    original = ReservationRepository.insert
    attempts = []

    async def invalid_insert(self, reservation):
        attempts.append(reservation.codigo)
        reservation.status = "INVALID"
        try:
            return await original(self, reservation)
        except IntegrityError as error:
            assert error.orig.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_CHECK
            raise

    monkeypatch.setattr(ReservationRepository, "insert", invalid_insert)
    if existing == "code":
        svc = ReservationService(session_factory, code_generator=lambda: winner.codigo)
    date = DAY if existing == "slot" else DAY + dt.timedelta(days=1)
    with pytest.raises(DomainError) as caught:
        await svc.create_confirmed_reservation("201", "quadra", date)
    assert type(caught.value) is DomainError
    assert len(attempts) == 1  # CHECK não provoca retry de código.
    assert "SQL" not in str(caught.value)
    async with session_factory() as session:
        rows = list(await session.scalars(select(Reserva).where(Reserva.data >= DAY)))
    assert [(r.codigo, r.status) for r in rows] == [(winner.codigo, "ATIVA")]


async def test_unique_conflict_survives_concurrent_cancellation(session_factory, monkeypatch):
    svc = ReservationService(session_factory)
    winner = await svc.create_confirmed_reservation("101", "quadra", DAY)
    original = ReservationRepository.insert

    async def cancel_after_conflict(self, reservation):
        try:
            return await original(self, reservation)
        except IntegrityError:
            # O repository já reverteu a tentativa. Outra operação altera o banco
            # antes que o Service classifique a exceção original.
            await svc.cancel_reservation("101", winner.codigo)
            raise

    monkeypatch.setattr(ReservationRepository, "insert", cancel_after_conflict)
    with pytest.raises(AreaUnavailableError):
        await svc.create_confirmed_reservation("201", "quadra", DAY)
    async with session_factory() as session:
        rows = list(await session.scalars(select(Reserva).where(Reserva.data == DAY)))
    assert [(r.codigo, r.status) for r in rows] == [(winner.codigo, "CANCELADA")]
    monkeypatch.setattr(ReservationRepository, "insert", original)
    assert (await svc.create_confirmed_reservation("201", "quadra", DAY)).status == "ATIVA"


async def _snapshot(factory):
    async with factory() as session:
        reservations_ = (await session.execute(
            select(Reserva.codigo, Reserva.apartamento, Reserva.area, Reserva.data, Reserva.status)
            .order_by(Reserva.codigo)
        )).all()
        visitors_ = (await session.execute(
            select(Visitante.id, Visitante.apartamento, Visitante.nome, Visitante.data)
            .order_by(Visitante.id)
        )).all()
    return reservations_, visitors_


@pytest.mark.parametrize("operation", ["reserve", "cancel", "visitor", "tool_reserve", "tool_cancel"])
async def test_real_lock_has_no_partial_effect_and_recovers(tools_wired, operation):
    factory = tools_wired
    svc = ReservationService(factory)
    vsvc = VisitorService(factory)

    async def execute():
        if operation == "reserve":
            return await svc.create_confirmed_reservation("101", "quadra", DAY)
        if operation == "cancel":
            return await svc.cancel_reservation("101", "RSV-1377")
        if operation == "visitor":
            return await vsvc.create_confirmed_authorization("101", "Teste de contenção", DAY)
        if operation == "tool_reserve":
            return await reservations.solicitar_reserva("quadra", DAY.isoformat(), ctx("101"))
        return await reservations.cancelar_minha_reserva("RSV-1377", ctx("101"))

    before = await _snapshot(factory)
    engine = factory.kw["bind"]
    lock = sqlite3.connect(engine.url.database)
    try:
        lock.execute("BEGIN IMMEDIATE")
        if operation.startswith("tool_"):
            result = await execute()
            assert result == {
                "status": "temporarily_unavailable",
                "message": "Serviço temporariamente ocupado. Tente novamente em instantes.",
            }
            assert "SQL" not in json.dumps(result)
        else:
            with pytest.raises(StorageBusyError) as caught:
                await execute()
            assert not isinstance(caught.value, AreaUnavailableError)
            assert "SQL" not in str(caught.value)
        assert await _snapshot(factory) == before
    finally:
        lock.rollback()
        lock.close()
    result = await execute()
    if operation.startswith("tool_"):
        assert result["status"] in ("created", "cancelled")
    assert await _snapshot(factory) != before


@pytest.mark.parametrize("tool_name,service_method,args", [
    ("listar_minhas_reservas", "list_active_reservations", ()),
    ("verificar_disponibilidade", "is_available", ("quadra", "2035-01-01")),
    ("solicitar_reserva", "request_reservation", ("quadra", "2035-01-01")),
    ("cancelar_minha_reserva", "cancel_reservation", ("RSV-1377",)),
    ("listar_meus_visitantes", "list_visitors", ()),
    ("solicitar_autorizacao_visitante", "request_authorization", ("Joana", "2035-01-01")),
])
async def test_all_tools_translate_busy(tools_wired, monkeypatch, tool_name, service_method, args):
    service_class = VisitorService if hasattr(VisitorService, service_method) else ReservationService
    module = visitors if service_class is VisitorService else reservations

    async def busy(*args, **kwargs):
        raise StorageBusyError()

    monkeypatch.setattr(service_class, service_method, busy)
    result = await getattr(module, tool_name)(*args, tool_context=ctx("101"))
    assert result["status"] == "temporarily_unavailable"


@pytest.mark.parametrize("code", [sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED, sqlite3.SQLITE_BUSY_SNAPSHOT, sqlite3.SQLITE_ERROR])
async def test_service_translates_only_busy_operational_errors(session_factory, monkeypatch, code):
    original = sqlite3.OperationalError("internal diagnostic")
    original.sqlite_errorcode = code
    error = OperationalError("SELECT private", {}, original)

    async def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(ReservationRepository, "list_by_apartment", fail)
    expected = OperationalError if code == sqlite3.SQLITE_ERROR else StorageBusyError
    with pytest.raises(expected):
        await ReservationService(session_factory).list_active_reservations("101")
