"""DTOs imutáveis devolvidos pelos Services (sem objetos ORM)."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import StrEnum


class RequestStatus(StrEnum):
    CREATED = "CREATED"
    REQUIRES_CONFIRMATION = "REQUIRES_CONFIRMATION"


@dataclass(frozen=True, slots=True)
class ReservationView:
    codigo: str
    area_id: str
    data: dt.date
    status: str


@dataclass(frozen=True, slots=True)
class ReservationRequestResult:
    status: RequestStatus
    area_id: str
    date: dt.date
    fee_cents: int
    reservation_code: str | None = None  # só preenchido quando CREATED


@dataclass(frozen=True, slots=True)
class VisitorView:
    nome: str
    data: dt.date


@dataclass(frozen=True, slots=True)
class VisitorAuthorizationRequestResult:
    status: RequestStatus  # sempre REQUIRES_CONFIRMATION
    visitor_name: str
    date: dt.date
