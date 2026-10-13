"""Rotas de verificação: leitura direta do domínio via Services (sem Agent nem Tool)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import get_reservation_service, get_visitor_service
from app.api.schemas import ErrorResponse, ReservationResponse, VisitorResponse
from app.services.reservation_service import ReservationService
from app.services.visitor_service import VisitorService

router = APIRouter(tags=["verificacao"])

_404 = {404: {"model": ErrorResponse}}


@router.get(
    "/apartamentos/{apartamento}/reservas",
    response_model=list[ReservationResponse],
    responses=_404,
)
async def listar_reservas(
    apartamento: str, service: ReservationService = Depends(get_reservation_service)
) -> list[ReservationResponse]:
    views = await service.list_active_reservations(apartamento)  # só ATIVAS
    return [ReservationResponse.from_view(v) for v in views]


@router.get(
    "/apartamentos/{apartamento}/visitantes",
    response_model=list[VisitorResponse],
    responses=_404,
)
async def listar_visitantes(
    apartamento: str, service: VisitorService = Depends(get_visitor_service)
) -> list[VisitorResponse]:
    views = await service.list_visitors(apartamento)
    return [VisitorResponse.from_view(v) for v in views]
