"""Consultas de apartamento usadas pela camada HTTP. Independente de IA, HTTP e ADK."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import Apartamento
from app.services._common import require_apartment
from app.services._persistence import service_session


class ApartmentService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory

    async def require_existing(self, apartment: str) -> str:
        """Devolve o número normalizado ou levanta ``ApartmentNotFoundError``."""
        async with service_session(self._factory) as session:
            return await require_apartment(session, apartment)

    async def is_initialized(self) -> bool:
        """True se o banco de domínio já foi populado (somente leitura; nunca cria nem limpa)."""
        try:
            async with service_session(self._factory) as session:
                return (await session.scalar(select(Apartamento.numero).limit(1))) is not None
        except OperationalError:
            return False
