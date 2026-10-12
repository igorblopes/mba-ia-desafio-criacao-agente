"""DTOs imutáveis devolvidos pelos Services (sem objetos ORM)."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


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


class ConfirmationStatus(StrEnum):
    """Ciclo de vida público de uma confirmação (``confirmacoes.status``).

    PENDING -> PROCESSING -> APPROVED | REJECTED   (PROCESSING -> PENDING só se seguro)

    APPROVED/REJECTED descrevem a RESPOSTA do usuário à confirmação, não o resultado de
    negócio: uma confirmação APPROVED pode ter terminado em ``unavailable``.
    """

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class ConfirmationRecord:
    id: str  # function_call_id da chamada adk_request_confirmation
    session_id: str
    invocation_id: str
    agent_name: str
    action: str
    details: dict[str, Any] = field(default_factory=dict)
    status: ConfirmationStatus = ConfirmationStatus.PENDING
    created_at: dt.datetime | None = None  # UTC
    responded_at: dt.datetime | None = None  # UTC
