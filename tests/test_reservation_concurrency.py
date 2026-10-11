"""Passo 4 — concorrência e robustez transacional das reservas.

Propriedade provada: duas decisões simultaneamente válidas não geram dois
estados simultaneamente inválidos. A garantia final é o índice único parcial
``uq_reservas_area_data_ativa`` (``UNIQUE(area, data) WHERE status = 'ATIVA'``).

Cada caso de uso do ``ReservationService`` abre a PRÓPRIA ``AsyncSession`` a
partir da fábrica, então cada tarefa concorrente tem sessão e transação
independentes sobre o mesmo arquivo SQLite temporário (nunca ``data/``).
Nenhum teste aqui usa ADK, Gemini, API ou ``is_available()`` como garantia.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import itertools

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.database.connection import BUSY_TIMEOUT_MS
from app.database.models import STATUS_ATIVA, STATUS_CANCELADA, Reserva
from app.domain.errors import AreaUnavailableError, DomainError
from app.repositories.reservation_repository import ReservationRepository
from app.services.reservation_service import ReservationService

D = dt.date
AREA = "salao-de-festas"
DATE = D(2030, 5, 11)
ITERATIONS = 25


@pytest.fixture
def service(session_factory):
    return ReservationService(session_factory)


async def _count_active(factory, area: str, date: dt.date) -> int:
    async with factory() as s:
        return await s.scalar(
            select(func.count())
            .select_from(Reserva)
            .where(Reserva.area == area, Reserva.data == date, Reserva.status == STATUS_ATIVA)
        )


async def _race(svc: ReservationService, area: str, date: dt.date, apts=("101", "201")):
    results = await asyncio.gather(
        *(svc.create_confirmed_reservation(a, area, date) for a in apts),
        return_exceptions=True,
    )
    wins = [r for r in results if not isinstance(r, BaseException)]
    losses = [r for r in results if isinstance(r, BaseException)]
    return wins, losses


def _assert_no_persistence_leak(exc: BaseException) -> None:
    text_ = f"{exc!s} {exc!r} {exc.args}"
    for forbidden in ("UNIQUE", "IntegrityError", "sqlite", "OperationalError", "locked"):
        assert forbidden not in text_


# --------------------------------------------------------------------------- #
# Esquema / PRAGMAs
# --------------------------------------------------------------------------- #


async def test_sqlite_pragmas_active_on_test_database(session_factory):
    async with session_factory() as s:
        assert (await s.scalar(text("PRAGMA journal_mode"))).lower() == "wal"
        assert await s.scalar(text("PRAGMA busy_timeout")) == BUSY_TIMEOUT_MS > 0
        assert await s.scalar(text("PRAGMA foreign_keys")) == 1


async def test_partial_unique_index_exists_with_active_predicate(session_factory):
    async with session_factory() as s:
        sql = await s.scalar(
            text("SELECT sql FROM sqlite_master WHERE name = 'uq_reservas_area_data_ativa'")
        )
    assert sql is not None
    normalized = " ".join(sql.upper().split())
    assert "UNIQUE INDEX" in normalized
    assert "(AREA, DATA)" in normalized
    assert "WHERE STATUS = 'ATIVA'" in normalized


async def test_database_rejects_two_active_even_bypassing_service(session_factory):
    """O índice vale para qualquer gravação, não só para o Service."""
    async with session_factory() as s:
        s.add(Reserva(codigo="RSV-RAW00001", apartamento="101", area=AREA, data=DATE, status=STATUS_ATIVA))
        await s.commit()
    async with session_factory() as s:
        s.add(Reserva(codigo="RSV-RAW00002", apartamento="201", area=AREA, data=DATE, status=STATUS_ATIVA))
        with pytest.raises(IntegrityError):
            await s.commit()
        await s.rollback()
    # CANCELADA + ATIVA na mesma área/data é permitido
    async with session_factory() as s:
        s.add(Reserva(codigo="RSV-RAW00003", apartamento="201", area=AREA, data=DATE, status=STATUS_CANCELADA))
        await s.commit()
    assert await _count_active(session_factory, AREA, DATE) == 1


# --------------------------------------------------------------------------- #
# Corrida principal
# --------------------------------------------------------------------------- #


async def test_only_one_concurrent_reservation_wins(service, session_factory):
    wins, losses = await _race(service, AREA, DATE)
    assert len(wins) == 1  # success_count
    assert len(losses) == 1  # failure_count
    assert await _count_active(session_factory, AREA, DATE) == 1
    # o vencedor retornado é exatamente a linha persistida
    async with session_factory() as s:
        rows = await ReservationRepository(s).list_by_area_and_date(AREA, DATE, STATUS_ATIVA)
    assert [r.codigo for r in rows] == [wins[0].codigo]


async def test_concurrent_loser_gets_area_unavailable(service):
    wins, losses = await _race(service, AREA, DATE)
    assert len(wins) == 1 and len(losses) == 1
    assert isinstance(losses[0], AreaUnavailableError)
    _assert_no_persistence_leak(losses[0])
    # não revela quem ganhou nem o código vencedor
    msg = f"{losses[0]!s} {losses[0]!r}"
    assert wins[0].codigo not in msg
    for apt_number in ("101", "201"):
        assert apt_number not in msg


async def test_concurrency_does_not_depend_on_availability_check(session_factory):
    """Nenhuma consulta de disponibilidade é feita: a segurança está na gravação."""

    class NoAvailabilityService(ReservationService):
        async def is_available(self, *a, **k):  # pragma: no cover - não deve ser chamado
            raise AssertionError("is_available() não pode participar da garantia")

    called = {"has_active_before_insert": 0}
    svc = NoAvailabilityService(session_factory)

    original = ReservationRepository.has_active

    async def spy(self, area, data):
        called["has_active_before_insert"] += 1
        return await original(self, area, data)

    # create_confirmed_reservation NÃO deve consultar disponibilidade antes do INSERT;
    # O diagnóstico também usa a exceção original, sem consulta posterior.
    ReservationRepository.has_active = spy  # type: ignore[method-assign]
    try:
        wins, losses = await _race(svc, AREA, DATE)
    finally:
        ReservationRepository.has_active = original  # type: ignore[method-assign]

    assert len(wins) == 1 and len(losses) == 1
    assert isinstance(losses[0], AreaUnavailableError)
    assert await _count_active(session_factory, AREA, DATE) == 1
    # A classificação não depende de um estado que pode mudar após o conflito.
    assert called["has_active_before_insert"] == 0


async def test_many_concurrent_requests_single_winner_and_final_state(service, session_factory):
    apts = ["101", "102", "201", "202", "301", "302"]
    wins, losses = await _race(service, "churrasqueira", D(2030, 6, 1), apts)
    assert len(wins) == 1
    assert len(losses) == 5
    assert all(isinstance(e, AreaUnavailableError) for e in losses)
    assert await _count_active(session_factory, "churrasqueira", D(2030, 6, 1)) == 1


async def test_repeated_concurrency_race(service, session_factory):
    base = D(2031, 1, 1)
    failures = 0
    duplicates = 0
    for i in range(ITERATIONS):
        date = base + dt.timedelta(days=i)
        # alterna a ordem de disparo para não favorecer sempre o mesmo apartamento
        apts = ("101", "201") if i % 2 == 0 else ("201", "101")
        wins, losses = await _race(service, AREA, date, apts)
        if len(wins) != 1 or len(losses) != 1 or not isinstance(losses[0], AreaUnavailableError):
            failures += 1
        if await _count_active(session_factory, AREA, date) != 1:
            duplicates += 1
    assert failures == 0
    assert duplicates == 0
    # visão global: nenhuma (área, data) ATIVA aparece mais de uma vez
    async with session_factory() as s:
        dup = (
            await s.execute(
                select(Reserva.area, Reserva.data, func.count())
                .where(Reserva.status == STATUS_ATIVA)
                .group_by(Reserva.area, Reserva.data)
                .having(func.count() > 1)
            )
        ).all()
    assert dup == []


# --------------------------------------------------------------------------- #
# Rollback
# --------------------------------------------------------------------------- #


async def test_conflict_rollback_allows_next_transaction(service, session_factory):
    wins, losses = await _race(service, AREA, DATE)
    assert isinstance(losses[0], AreaUnavailableError)
    loser_apt = "201" if await _winner_apt(session_factory, wins[0].codigo) == "101" else "101"
    # o perdedor segue operando (sem PendingRollbackError) em outra data
    other = await service.create_confirmed_reservation(loser_apt, AREA, D(2030, 5, 12))
    assert other.status == STATUS_ATIVA
    assert await _count_active(session_factory, AREA, D(2030, 5, 12)) == 1


async def _winner_apt(factory, codigo: str) -> str:
    async with factory() as s:
        return (await ReservationRepository(s).get(codigo)).apartamento


async def test_repository_rollback_keeps_session_usable_after_integrity_error(session_factory):
    """Mesma sessão: depois do IntegrityError no repository, nova transação funciona."""
    async with session_factory() as s:
        repo = ReservationRepository(s)
        await repo.insert(
            Reserva(codigo="RSV-AAAA0001", apartamento="101", area=AREA, data=DATE, status=STATUS_ATIVA)
        )
        await s.commit()
    async with session_factory() as s:
        repo = ReservationRepository(s)
        with pytest.raises(IntegrityError):
            await repo.insert(
                Reserva(codigo="RSV-AAAA0002", apartamento="201", area=AREA, data=DATE, status=STATUS_ATIVA)
            )
        # sem PendingRollbackError: a sessão já sofreu rollback
        assert await s.scalar(text("SELECT 1")) == 1
        await repo.insert(
            Reserva(codigo="RSV-AAAA0003", apartamento="201", area=AREA, data=D(2030, 5, 12), status=STATUS_ATIVA)
        )
        await s.commit()
    assert await _count_active(session_factory, AREA, D(2030, 5, 12)) == 1
    assert await _count_active(session_factory, AREA, DATE) == 1


# --------------------------------------------------------------------------- #
# Cancelamento libera área/data
# --------------------------------------------------------------------------- #


async def test_cancelled_reservation_releases_area_date(service, session_factory):
    first = await service.create_confirmed_reservation("101", AREA, DATE)
    with pytest.raises(AreaUnavailableError):
        await service.create_confirmed_reservation("201", AREA, DATE)

    await service.cancel_reservation("101", first.codigo)
    second = await service.create_confirmed_reservation("201", AREA, DATE)

    assert second.codigo != first.codigo
    async with session_factory() as s:
        repo = ReservationRepository(s)
        r1, r2 = await repo.get(first.codigo), await repo.get(second.codigo)
    assert (r1.apartamento, r1.status) == ("101", STATUS_CANCELADA)
    assert (r2.apartamento, r2.status) == ("201", STATUS_ATIVA)
    assert await _count_active(session_factory, AREA, DATE) == 1


# --------------------------------------------------------------------------- #
# Códigos de reserva
# --------------------------------------------------------------------------- #


async def test_reservation_codes_remain_unique_under_concurrency(service, session_factory):
    apts = ["101", "102", "201", "202", "301", "302"]
    dates = [D(2032, 1, d) for d in range(1, 11)]
    results = await asyncio.gather(
        *(service.create_confirmed_reservation(a, "quadra", d) for d in dates for a in apts),
        return_exceptions=True,
    )
    wins = [r for r in results if not isinstance(r, BaseException)]
    errors = [r for r in results if isinstance(r, BaseException)]
    assert len(wins) == len(dates)  # exatamente um vencedor por data
    assert all(isinstance(e, AreaUnavailableError) for e in errors)
    codes = [w.codigo for w in wins]
    assert len(set(codes)) == len(codes)
    async with session_factory() as s:
        all_codes = [r.codigo for r in await ReservationRepository(s).list_all()]
    assert len(set(all_codes)) == len(all_codes)  # PK UNIQUE(codigo) preservada


async def test_code_collision_retries_with_new_code_and_is_not_area_unavailable(session_factory):
    """Colisão de código ≠ indisponibilidade: rollback, novo código, reserva criada."""
    seq = itertools.chain(["RSV-1377"], (f"RSV-NEW{i:05d}" for i in itertools.count()))
    svc = ReservationService(session_factory, code_generator=lambda: next(seq))
    # RSV-1377 já existe (101/quadra/2030-03-09, ativa); a data pedida está livre
    view = await svc.create_confirmed_reservation("101", AREA, D(2031, 2, 1))
    assert view.codigo == "RSV-NEW00000"
    assert view.status == STATUS_ATIVA
    assert await _count_active(session_factory, AREA, D(2031, 2, 1)) == 1


async def test_area_conflict_is_not_retried_as_code_collision(session_factory):
    calls = {"n": 0}

    def gen() -> str:
        calls["n"] += 1
        return f"RSV-GEN{calls['n']:05d}"

    svc = ReservationService(session_factory, code_generator=gen)
    await svc.create_confirmed_reservation("101", AREA, DATE)
    before = calls["n"]
    with pytest.raises(AreaUnavailableError):
        await svc.create_confirmed_reservation("201", AREA, DATE)
    assert calls["n"] - before == 1  # um único código gerado: sem retry por conflito de área


async def test_unexpected_integrity_error_is_not_masked(session_factory):
    """Violação de FK não é indisponibilidade de área nem colisão de código."""
    svc = ReservationService(session_factory)

    original = ReservationRepository.insert

    async def bad_insert(self, reserva):
        reserva.apartamento = "999-inexistente"  # viola FK apartamentos.numero
        return await original(self, reserva)

    ReservationRepository.insert = bad_insert  # type: ignore[method-assign]
    try:
        with pytest.raises(DomainError) as exc:
            await svc.create_confirmed_reservation("101", AREA, D(2031, 3, 3))
    finally:
        ReservationRepository.insert = original  # type: ignore[method-assign]
    assert not isinstance(exc.value, AreaUnavailableError)  # erro distinto, não mascarado
    _assert_no_persistence_leak(exc.value)
    assert await _count_active(session_factory, AREA, D(2031, 3, 3)) == 0
