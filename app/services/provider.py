"""Montagem (wiring) dos Services a partir da fábrica de sessões do banco.

Existe para que as Tools obtenham Services sem importar SQLAlchemy, Repositories
nem a camada de banco. Testes podem substituir a fábrica com
``configure_services`` e restaurar o padrão com ``reset_services``.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.reservation_service import ReservationService
from app.services.visitor_service import VisitorService

_reservation_service: ReservationService | None = None
_visitor_service: VisitorService | None = None


def configure_services(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Define os Services a partir de uma fábrica de sessões explícita."""
    global _reservation_service, _visitor_service
    _reservation_service = ReservationService(session_factory)
    _visitor_service = VisitorService(session_factory)


def reset_services() -> None:
    global _reservation_service, _visitor_service
    _reservation_service = None
    _visitor_service = None


def _ensure() -> None:
    if _reservation_service is None or _visitor_service is None:
        from app.database.connection import get_session_factory  # import tardio

        configure_services(get_session_factory())


def get_reservation_service() -> ReservationService:
    _ensure()
    assert _reservation_service is not None
    return _reservation_service


def get_visitor_service() -> VisitorService:
    _ensure()
    assert _visitor_service is not None
    return _visitor_service
