"""Validações compartilhadas pelos Services (somente leitura)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Area
from app.domain.errors import ApartmentNotFoundError, AreaNotFoundError
from app.repositories.apartment_repository import ApartmentRepository
from app.repositories.area_repository import AreaRepository


def normalize_apartment(apartment: str) -> str:
    return str(apartment).strip()


async def require_apartment(session: AsyncSession, apartment: str) -> str:
    numero = normalize_apartment(apartment)
    if await ApartmentRepository(session).get(numero) is None:
        raise ApartmentNotFoundError()
    return numero


async def require_area(session: AsyncSession, area_id: str) -> Area:
    area = await AreaRepository(session).get(str(area_id).strip())
    if area is None:
        raise AreaNotFoundError()
    return area
