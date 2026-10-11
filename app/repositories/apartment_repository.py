"""Persistência de apartamentos. Sem regras de negócio."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Apartamento


class ApartmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, numero: str) -> Apartamento | None:
        return await self._session.get(Apartamento, numero)

    async def list_all(self) -> list[Apartamento]:
        result = await self._session.scalars(select(Apartamento).order_by(Apartamento.numero))
        return list(result)
