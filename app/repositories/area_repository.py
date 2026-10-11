"""Persistência de áreas comuns. Sem regras de negócio."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Area


class AreaRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, area_id: str) -> Area | None:
        return await self._session.get(Area, area_id)

    async def list_all(self) -> list[Area]:
        result = await self._session.scalars(select(Area).order_by(Area.id))
        return list(result)
