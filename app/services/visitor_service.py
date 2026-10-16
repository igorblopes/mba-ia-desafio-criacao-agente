"""Casos de uso de visitantes. Independente de IA, HTTP e ADK.

``apartment`` é CONTEXTO CONFIÁVEL da camada de aplicação (vem de
``session.state["apartamento"]`` via ``ToolContext``). O modelo nunca o escolhe.

``request_authorization`` nunca grava: autorizar visitante libera acesso ao
prédio e sempre exige confirmação. ``create_confirmed_authorization`` é função
interna, chamada apenas após a confirmação externa ter sido validada.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import Visitante
from app.domain.errors import InvalidVisitorNameError
from app.domain.types import RequestStatus, VisitorAuthorizationRequestResult, VisitorView
from app.repositories.visitor_repository import VisitorRepository
from app.services._common import require_apartment
from app.services._persistence import service_session


def _clean_name(name: str) -> str:
    cleaned = " ".join(str(name).split())
    if not cleaned:
        raise InvalidVisitorNameError()
    return cleaned


class VisitorService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory

    async def list_visitors(self, apartment: str) -> list[VisitorView]:
        async with service_session(self._factory) as session:
            numero = await require_apartment(session, apartment)
            rows = await VisitorRepository(session).list_by_apartment(numero)
            return [VisitorView(nome=v.nome, data=v.data) for v in rows]

    async def request_authorization(
        self, apartment: str, visitor_name: str, date: dt.date
    ) -> VisitorAuthorizationRequestResult:
        async with service_session(self._factory) as session:
            await require_apartment(session, apartment)
        return VisitorAuthorizationRequestResult(
            status=RequestStatus.REQUIRES_CONFIRMATION,
            visitor_name=_clean_name(visitor_name),
            date=date,
        )

    async def create_confirmed_authorization(
        self, apartment: str, visitor_name: str, date: dt.date
    ) -> VisitorView:
        """INTERNA: executa após confirmação externa validada. Não exposta ao modelo."""
        name = _clean_name(visitor_name)
        async with service_session(self._factory) as session:
            try:
                numero = await require_apartment(session, apartment)
                await VisitorRepository(session).insert(
                    Visitante(apartamento=numero, nome=name, data=date)
                )
                await session.commit()
            except BaseException:
                await session.rollback()
                raise
        return VisitorView(nome=name, data=date)
