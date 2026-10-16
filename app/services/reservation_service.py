"""Casos de uso de reservas. Independente de IA, HTTP e ADK.

``apartment`` é CONTEXTO CONFIÁVEL da camada de aplicação (vem de
``session.state["apartamento"]`` via ``ToolContext``). O modelo nunca o escolhe.

Dois caminhos distintos, sem parâmetro ``confirmed``:

* ``request_reservation``          – decide; área paga NÃO grava nada.
* ``create_confirmed_reservation`` – função interna, chamada só após a
  confirmação externa ter sido validada.

A exclusividade área/data é garantida pelo índice único parcial do banco; a
consulta de disponibilidade é apenas UX. Cada caso de uso usa sua própria
sessão/transação; falha de escrita sempre faz rollback.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import STATUS_ATIVA, STATUS_CANCELADA, Reserva
from app.domain.errors import (
    AreaUnavailableError,
    DomainError,
    ReservationCodeGenerationError,
    ReservationNotFoundError,
)
from app.domain.types import ReservationRequestResult, ReservationView, RequestStatus
from app.repositories.reservation_repository import ReservationRepository
from app.services._common import require_apartment, require_area
from app.services._persistence import is_unique_violation, service_session

MAX_CODE_ATTEMPTS = 5


def generate_reservation_code() -> str:
    """Código gerado pelo sistema, ex.: ``RSV-A83F72C1`` (32 bits aleatórios)."""
    return f"RSV-{uuid.uuid4().hex[:8].upper()}"


def _view(r: Reserva) -> ReservationView:
    return ReservationView(codigo=r.codigo, area_id=r.area, data=r.data, status=r.status)


class ReservationService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        code_generator: Callable[[], str] = generate_reservation_code,
        max_code_attempts: int = MAX_CODE_ATTEMPTS,
    ) -> None:
        self._factory = session_factory
        self._code_generator = code_generator
        self._max_attempts = max_code_attempts

    async def list_active_reservations(self, apartment: str) -> list[ReservationView]:
        """Reservas ATIVAS do apartamento; o filtro é aplicado na consulta SQL."""
        async with service_session(self._factory) as session:
            numero = await require_apartment(session, apartment)
            rows = await ReservationRepository(session).list_by_apartment(
                numero, status=STATUS_ATIVA
            )
            return [_view(r) for r in rows]

    async def is_available(self, area_id: str, date: dt.date) -> bool:
        """Apenas True/False; nunca identifica quem reservou. Não é a garantia final."""
        async with service_session(self._factory) as session:
            area = await require_area(session, area_id)
            return not await ReservationRepository(session).has_active(area.id, date)

    async def request_reservation(
        self, apartment: str, area_id: str, date: dt.date
    ) -> ReservationRequestResult:
        """Área gratuita → cria (CREATED). Área paga → REQUIRES_CONFIRMATION, sem gravar."""
        async with service_session(self._factory) as session:
            numero = await require_apartment(session, apartment)
            area = await require_area(session, area_id)
            available = not await ReservationRepository(session).has_active(area.id, date)
            fee, resolved_area = area.taxa_centavos, area.id

        if not available:  # só UX: evita pedir confirmação de algo já ocupado
            raise AreaUnavailableError()

        if fee > 0:
            return ReservationRequestResult(
                status=RequestStatus.REQUIRES_CONFIRMATION,
                area_id=resolved_area,
                date=date,
                fee_cents=fee,
            )

        created = await self._insert_reservation(numero, resolved_area, date)
        return ReservationRequestResult(
            status=RequestStatus.CREATED,
            area_id=resolved_area,
            date=date,
            fee_cents=fee,
            reservation_code=created.codigo,
        )

    async def create_confirmed_reservation(
        self, apartment: str, area_id: str, date: dt.date
    ) -> ReservationView:
        """INTERNA: executa após confirmação externa validada. Não exposta ao modelo."""
        async with service_session(self._factory) as session:
            numero = await require_apartment(session, apartment)
            area = await require_area(session, area_id)
            resolved_area = area.id
        return await self._insert_reservation(numero, resolved_area, date)

    async def cancel_reservation(
        self, apartment: str, reservation_code: str
    ) -> ReservationView:
        """Cancela reserva ATIVA do próprio apartamento (sem confirmação, sem apagar).

        Reserva de outro apartamento é indistinguível de inexistente.
        """
        code = str(reservation_code).strip().upper()
        async with service_session(self._factory) as session:
            try:
                numero = await require_apartment(session, apartment)
                repo = ReservationRepository(session)
                found = await repo.get_by_apartment_and_code(numero, code, STATUS_ATIVA)
                if found is None:
                    raise ReservationNotFoundError()
                await repo.set_status(found.codigo, STATUS_CANCELADA)
                await session.commit()
                return ReservationView(
                    codigo=found.codigo,
                    area_id=found.area,
                    data=found.data,
                    status=STATUS_CANCELADA,
                )
            except BaseException:
                await session.rollback()
                raise

    async def _insert_reservation(
        self, apartment: str, area_id: str, date: dt.date
    ) -> ReservationView:
        for _ in range(self._max_attempts):
            code = self._code_generator()
            async with service_session(self._factory) as session:
                repo = ReservationRepository(session)
                try:
                    reserva = Reserva(
                        codigo=code,
                        apartamento=apartment,
                        area=area_id,
                        data=date,
                        status=STATUS_ATIVA,
                    )
                    await repo.insert(reserva)  # rollback feito pelo repository em caso de erro
                    await session.commit()
                    return _view(reserva)
                except IntegrityError as error:
                    await session.rollback()
                    if is_unique_violation(error, "reservas.area, reservas.data"):
                        raise AreaUnavailableError() from None
                    if is_unique_violation(error, "reservas.codigo"):
                        continue  # PK inclui códigos de reservas canceladas.
                    raise DomainError("Não foi possível registrar a reserva.") from None
                except BaseException:
                    await session.rollback()
                    raise

        raise ReservationCodeGenerationError()
