"""Validações compartilhadas pelos Services (somente leitura)."""

from __future__ import annotations

import re
import unicodedata

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


def area_key(value: str) -> str:
    """Forma canônica de um identificador/nome de área: sem acento, minúsculo, separador '-'.

    "salao_de_festas", "Salão de Festas" e "salao-de-festas" viram a mesma chave.
    """
    plain = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")


async def require_area(session: AsyncSession, area_id: str) -> Area:
    """Área pelo id exato; senão, pela forma canônica do id ou do nome (match único)."""
    repo = AreaRepository(session)
    area = await repo.get(str(area_id).strip())
    if area is not None:
        return area
    key = area_key(area_id)
    matches = [a for a in await repo.list_all() if key and key in (area_key(a.id), area_key(a.nome))]
    if len(matches) != 1:
        raise AreaNotFoundError()
    return matches[0]
