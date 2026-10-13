"""Contrato HTTP (schemas Pydantic). Nenhuma regra de domínio aqui."""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, Field, StrictBool, field_validator

from app.domain.types import ConfirmationRecord, ReservationView, VisitorView


def _not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("não pode ser vazio")
    return value


class CreateSessionRequest(BaseModel):
    apartamento: str = Field(min_length=1)

    @field_validator("apartamento")
    @classmethod
    def _apartamento_nao_vazio(cls, value: str) -> str:
        return _not_blank(value)


class CreateSessionResponse(BaseModel):
    session_id: str


class SendMessageRequest(BaseModel):
    texto: str = Field(min_length=1)

    @field_validator("texto")
    @classmethod
    def _texto_nao_vazio(cls, value: str) -> str:
        return _not_blank(value)


class RespondConfirmationRequest(BaseModel):
    id: str = Field(min_length=1)
    confirmado: StrictBool


class PendingConfirmationResponse(BaseModel):
    """Vista pública: sem invocation_id, agent_name, status interno nem chaves de banco."""

    id: str
    acao: str
    detalhes: dict[str, Any]

    @classmethod
    def from_record(cls, record: ConfirmationRecord) -> PendingConfirmationResponse:
        return cls(id=record.id, acao=record.action, detalhes=dict(record.details))


class ConversationResponse(BaseModel):
    """Envelope único de ``/mensagens`` e ``/confirmacoes``."""

    resposta: str
    confirmacoes_pendentes: list[PendingConfirmationResponse]

    @classmethod
    def build(
        cls, reply: str, pending: list[ConfirmationRecord]
    ) -> ConversationResponse:
        return cls(
            resposta=reply,
            confirmacoes_pendentes=[PendingConfirmationResponse.from_record(p) for p in pending],
        )


class ReservationResponse(BaseModel):
    codigo: str
    area: str
    data: dt.date

    @classmethod
    def from_view(cls, view: ReservationView) -> ReservationResponse:
        return cls(codigo=view.codigo, area=view.area_id, data=view.data)


class VisitorResponse(BaseModel):
    nome: str
    data: dt.date

    @classmethod
    def from_view(cls, view: VisitorView) -> VisitorResponse:
        return cls(nome=view.nome, data=view.data)


class ErrorResponse(BaseModel):
    detail: str
