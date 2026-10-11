"""Persistência de reservas. Somente operações primitivas, sem regras de negócio.

Conflitos de unicidade (código repetido ou segunda reserva ATIVA para a mesma
área/data) chegam como ``sqlalchemy.exc.IntegrityError`` lançada pelo banco.
O repository faz ``rollback`` para a sessão continuar utilizável e relança a
exceção; traduzi-la em resposta de negócio é papel das camadas superiores.

Observação: ``rollback`` descarta todo o trabalho pendente da transação
corrente da sessão, não só a inserção que falhou.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Reserva


class ReservationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, codigo: str) -> Reserva | None:
        return await self._session.get(Reserva, codigo)

    async def list_all(self) -> list[Reserva]:
        result = await self._session.scalars(select(Reserva).order_by(Reserva.codigo))
        return list(result)

    async def list_by_apartment(
        self, apartamento: str, status: str | None = None
    ) -> list[Reserva]:
        stmt = select(Reserva).where(Reserva.apartamento == apartamento)
        if status is not None:
            stmt = stmt.where(Reserva.status == status)
        result = await self._session.scalars(stmt.order_by(Reserva.data, Reserva.codigo))
        return list(result)

    async def list_by_area_and_date(
        self, area: str, data: dt.date, status: str | None = None
    ) -> list[Reserva]:
        stmt = select(Reserva).where(Reserva.area == area, Reserva.data == data)
        if status is not None:
            stmt = stmt.where(Reserva.status == status)
        result = await self._session.scalars(stmt.order_by(Reserva.codigo))
        return list(result)

    async def insert(self, reserva: Reserva) -> Reserva:
        """Grava a reserva (flush). A transação é confirmada por quem chamou."""
        self._session.add(reserva)
        try:
            await self._session.flush()
        except IntegrityError:
            await self._session.rollback()
            raise
        return reserva

    async def set_status(self, codigo: str, status: str) -> bool:
        """Altera apenas o status. Retorna False se o código não existe."""
        try:
            result = await self._session.execute(
                update(Reserva).where(Reserva.codigo == codigo).values(status=status)
            )
            await self._session.flush()
        except IntegrityError:
            await self._session.rollback()
            raise
        return result.rowcount > 0
