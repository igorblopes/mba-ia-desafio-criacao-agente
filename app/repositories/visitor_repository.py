"""Persistência de visitantes. Sem regras de negócio."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Visitante


class VisitorRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_by_apartment(self, apartamento: str) -> list[Visitante]:
        result = await self._session.scalars(
            select(Visitante)
            .where(Visitante.apartamento == apartamento)
            .order_by(Visitante.data, Visitante.id)
        )
        return list(result)

    async def list_all(self) -> list[Visitante]:
        result = await self._session.scalars(select(Visitante).order_by(Visitante.id))
        return list(result)

    async def insert(self, visitante: Visitante) -> Visitante:
        self._session.add(visitante)
        await self._session.flush()
        return visitante
