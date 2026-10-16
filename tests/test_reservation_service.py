from __future__ import annotations

import asyncio
import datetime as dt
import itertools

import pytest
from sqlalchemy import func, select

from app.database.models import STATUS_ATIVA, STATUS_CANCELADA, Reserva
from app.domain.errors import (
    ApartmentNotFoundError,
    AreaNotFoundError,
    AreaUnavailableError,
    DomainError,
    ReservationCodeGenerationError,
    ReservationNotFoundError,
)
from app.domain.types import RequestStatus, ReservationView
from app.services.reservation_service import ReservationService, generate_reservation_code

D = dt.date


@pytest.fixture
def service(session_factory):
    return ReservationService(session_factory)


async def _all(factory) -> list[Reserva]:
    async with factory() as s:
        return list(await s.scalars(select(Reserva).order_by(Reserva.codigo)))


async def test_list_isolated_by_apartment(service):
    codes = {r.codigo for r in await service.list_active_reservations("101")}
    assert "RSV-1377" in codes
    assert "RSV-4821" not in codes


async def test_list_only_active(service):
    await service.cancel_reservation("101", "RSV-1377")
    assert await service.list_active_reservations("101") == []


async def test_unknown_apartment_and_area(service):
    with pytest.raises(ApartmentNotFoundError):
        await service.list_active_reservations("999")
    with pytest.raises(AreaNotFoundError):
        await service.is_available("piscina", D(2030, 1, 1))
    with pytest.raises(AreaNotFoundError):
        await service.request_reservation("101", "piscina", D(2030, 1, 1))


async def test_cancel_own(service, session_factory):
    before = len(await _all(session_factory))
    view = await service.cancel_reservation("101", "RSV-1377")
    assert view.status == STATUS_CANCELADA
    rows = await _all(session_factory)
    assert len(rows) == before  # não apagou
    r = next(r for r in rows if r.codigo == "RSV-1377")
    assert (r.status, r.apartamento, r.area, r.data) == (
        STATUS_CANCELADA, "101", "quadra", D(2030, 3, 9)
    )


async def test_cancel_twice_is_not_found(service):
    await service.cancel_reservation("101", "RSV-1377")
    with pytest.raises(ReservationNotFoundError):
        await service.cancel_reservation("101", "RSV-1377")


async def test_cancel_other_apartment_is_not_found_and_leaks_nothing(service, session_factory):
    with pytest.raises(ReservationNotFoundError) as exc:
        await service.cancel_reservation("101", "RSV-4821")
    msg = f"{exc.value!s} {exc.value!r} {exc.value.args}"
    for secret in ("302", "RSV-4821", "Rafael", "Moreira"):
        assert secret not in msg
    r = next(r for r in await _all(session_factory) if r.codigo == "RSV-4821")
    assert (r.status, r.apartamento) == (STATUS_ATIVA, "302")


async def test_cancel_nonexistent_same_error_as_foreign(service):
    with pytest.raises(ReservationNotFoundError) as foreign:
        await service.cancel_reservation("101", "RSV-4821")
    with pytest.raises(ReservationNotFoundError) as missing:
        await service.cancel_reservation("101", "RSV-0000")
    assert str(foreign.value) == str(missing.value)


async def test_cancel_needs_no_confirmation(service):
    view = await service.cancel_reservation("101", "RSV-1377")
    assert isinstance(view, ReservationView)  # executa direto; sem estado de confirmação
    assert view.status == STATUS_CANCELADA


async def test_free_area_creates(service, session_factory):
    res = await service.request_reservation("101", "quadra", D(2030, 4, 6))
    assert res.status is RequestStatus.CREATED
    assert res.fee_cents == 0
    assert res.reservation_code and res.reservation_code.startswith("RSV-")
    r = next(r for r in await _all(session_factory) if r.codigo == res.reservation_code)
    assert (r.apartamento, r.area, r.data, r.status) == ("101", "quadra", D(2030, 4, 6), STATUS_ATIVA)


@pytest.mark.parametrize(("area", "fee"), [("salao-de-festas", 15000), ("churrasqueira", 8000)])
async def test_paid_area_requires_confirmation_and_does_not_write(service, session_factory, area, fee):
    before = await _all(session_factory)
    res = await service.request_reservation("101", area, D(2030, 4, 6))
    assert res.status is RequestStatus.REQUIRES_CONFIRMATION
    assert res.fee_cents == fee
    assert res.reservation_code is None
    assert [r.codigo for r in await _all(session_factory)] == [r.codigo for r in before]


async def test_confirmed_reservation_creates(service, session_factory):
    before = len(await _all(session_factory))
    view = await service.create_confirmed_reservation("101", "salao-de-festas", D(2030, 4, 6))
    assert view.status == STATUS_ATIVA
    assert len(await _all(session_factory)) == before + 1


async def test_occupied_date_raises_without_leak(service, session_factory):
    with pytest.raises(AreaUnavailableError) as exc:
        await service.create_confirmed_reservation("101", "salao-de-festas", D(2030, 3, 16))
    msg = f"{exc.value!s} {exc.value!r}"
    for secret in ("302", "RSV-4821", "Rafael", "UNIQUE", "IntegrityError", "sqlite"):
        assert secret not in msg
    # sessão/serviço continuam utilizáveis após o erro (rollback correto)
    ok = await service.create_confirmed_reservation("101", "salao-de-festas", D(2030, 3, 17))
    assert ok.status == STATUS_ATIVA


async def test_free_area_occupied_raises(service):
    with pytest.raises(AreaUnavailableError):
        await service.request_reservation("201", "quadra", D(2030, 3, 9))


async def test_paid_area_occupied_raises_before_asking_confirmation(service):
    with pytest.raises(AreaUnavailableError):
        await service.request_reservation("101", "salao-de-festas", D(2030, 3, 16))


async def test_is_available_boolean_only(service):
    assert await service.is_available("quadra", D(2030, 3, 9)) is False
    assert await service.is_available("quadra", D(2030, 3, 10)) is True


async def test_cancelled_slot_becomes_available_again(service):
    await service.cancel_reservation("302", "RSV-4821")
    assert await service.is_available("salao-de-festas", D(2030, 3, 16)) is True
    view = await service.create_confirmed_reservation("101", "salao-de-festas", D(2030, 3, 16))
    assert view.status == STATUS_ATIVA


async def test_codes_unique(service):
    codes = []
    for day in range(1, 11):
        v = await service.create_confirmed_reservation("101", "quadra", D(2031, 1, day))
        codes.append(v.codigo)
    assert len(set(codes)) == len(codes)
    assert all(c.startswith("RSV-") for c in codes)


async def test_generator_format():
    c = generate_reservation_code()
    assert c.startswith("RSV-") and len(c) == 12


async def test_cancelled_code_not_reused(session_factory):
    await ReservationService(session_factory).cancel_reservation("101", "RSV-1377")
    # gerador malicioso/azarado que devolve o código cancelado primeiro
    seq = itertools.chain(["RSV-1377"], (f"RSV-NEW{i:05d}" for i in itertools.count()))
    svc = ReservationService(session_factory, code_generator=lambda: next(seq))
    v = await svc.create_confirmed_reservation("101", "quadra", D(2031, 2, 1))
    assert v.codigo != "RSV-1377"
    rows = {r.codigo: r for r in await _all(session_factory)}
    assert rows["RSV-1377"].status == STATUS_CANCELADA


async def test_new_codes_never_equal_cancelled(service, session_factory):
    await service.cancel_reservation("101", "RSV-1377")
    new = [
        (await service.create_confirmed_reservation("101", "quadra", D(2031, 3, d))).codigo
        for d in range(1, 8)
    ]
    assert "RSV-1377" not in new


async def test_code_exhaustion_raises(session_factory):
    svc = ReservationService(session_factory, code_generator=lambda: "RSV-1377", max_code_attempts=3)
    with pytest.raises(ReservationCodeGenerationError):
        await svc.create_confirmed_reservation("101", "quadra", D(2031, 2, 1))
    assert not any(
        r.data == D(2031, 2, 1) for r in await _all(session_factory)
    )


async def test_concurrent_creation_single_winner(session_factory):
    svc = ReservationService(session_factory)
    date = D(2030, 5, 11)
    results = await asyncio.gather(
        svc.create_confirmed_reservation("101", "salao-de-festas", date),
        svc.create_confirmed_reservation("201", "salao-de-festas", date),
        return_exceptions=True,
    )
    ok = [r for r in results if not isinstance(r, BaseException)]
    errs = [r for r in results if isinstance(r, BaseException)]
    assert len(ok) == 1 and len(errs) == 1
    assert isinstance(errs[0], AreaUnavailableError)
    async with session_factory() as s:
        n = await s.scalar(
            select(func.count()).select_from(Reserva).where(
                Reserva.area == "salao-de-festas",
                Reserva.data == date,
                Reserva.status == STATUS_ATIVA,
            )
        )
    assert n == 1


async def test_concurrent_many_single_winner(session_factory):
    svc = ReservationService(session_factory)
    date = D(2030, 6, 1)
    apts = ["101", "102", "201", "202", "301", "302"]
    results = await asyncio.gather(
        *(svc.create_confirmed_reservation(a, "churrasqueira", date) for a in apts),
        return_exceptions=True,
    )
    assert sum(not isinstance(r, BaseException) for r in results) == 1
    assert all(
        isinstance(r, AreaUnavailableError) for r in results if isinstance(r, BaseException)
    )


async def test_domain_errors_share_base():
    assert issubclass(AreaUnavailableError, DomainError)
    assert issubclass(ReservationNotFoundError, DomainError)


@pytest.mark.parametrize("given", ["salao_de_festas", "Salão de festas", " SALAO-DE-FESTAS "])
async def test_area_id_variants_resolve_to_canonical_id(service, session_factory, given):
    """Regressão (Passo 12): o Gemini mandou "salao_de_festas" e a reserva paga não foi pedida."""
    result = await service.request_reservation("101", given, D(2030, 4, 20))
    assert result.status is RequestStatus.REQUIRES_CONFIRMATION
    assert result.area_id == "salao-de-festas"
    view = await service.create_confirmed_reservation("101", given, D(2030, 4, 20))
    assert view.area_id == "salao-de-festas"
    assert await service.is_available("salao_de_festas", D(2030, 4, 20)) is False


@pytest.mark.parametrize("given", ["salao", "festas", "piscina", "", "-"])
async def test_area_partial_or_unknown_names_still_not_found(service, given):
    with pytest.raises(AreaNotFoundError):
        await service.request_reservation("101", given, D(2030, 4, 20))
