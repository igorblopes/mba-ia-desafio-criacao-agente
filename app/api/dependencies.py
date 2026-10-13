"""Dependências injetadas nos endpoints. Nada pesado é criado por request."""

from __future__ import annotations

from fastapi import Request

from app.runtime.adk_runtime import AdkRuntime
from app.services.apartment_service import ApartmentService
from app.services.provider import (
    get_apartment_service as _apartment_service,
    get_reservation_service as _reservation_service,
    get_visitor_service as _visitor_service,
)
from app.services.reservation_service import ReservationService
from app.services.visitor_service import VisitorService


def get_runtime(request: Request) -> AdkRuntime:
    return request.app.state.adk_runtime


def get_apartment_service() -> ApartmentService:
    return _apartment_service()


def get_reservation_service() -> ReservationService:
    return _reservation_service()


def get_visitor_service() -> VisitorService:
    return _visitor_service()
