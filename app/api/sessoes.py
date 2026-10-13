"""Sessões, mensagens e eventos. Encaminha ao ``AdkRuntime``; não decide nada."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status

from app.api.dependencies import get_apartment_service, get_runtime
from app.api.schemas import (
    ConversationResponse,
    CreateSessionRequest,
    CreateSessionResponse,
    ErrorResponse,
    SendMessageRequest,
)
from app.runtime.adk_runtime import AdkRuntime
from app.services.apartment_service import ApartmentService

router = APIRouter(tags=["sessoes"])

_404 = {404: {"model": ErrorResponse}}


@router.post(
    "/sessoes",
    status_code=status.HTTP_201_CREATED,
    response_model=CreateSessionResponse,
    responses=_404,
)
async def criar_sessao(
    body: CreateSessionRequest,
    runtime: AdkRuntime = Depends(get_runtime),
    apartments: ApartmentService = Depends(get_apartment_service),
) -> CreateSessionResponse:
    apartment = await apartments.require_existing(body.apartamento)  # 404 se não existir
    info = await runtime.create_session(apartment)  # state["apartamento"] gravado aqui
    return CreateSessionResponse(session_id=info.id)


@router.post(
    "/sessoes/{session_id}/mensagens",
    response_model=ConversationResponse,
    responses=_404,
)
async def enviar_mensagem(
    session_id: str,
    body: SendMessageRequest,
    runtime: AdkRuntime = Depends(get_runtime),
) -> ConversationResponse:
    result = await runtime.send_message(session_id, body.texto)
    return ConversationResponse.build(result.reply, result.pending_confirmations)


@router.get(
    "/sessoes/{session_id}/eventos",
    response_model=list[dict[str, Any]],
    responses=_404,
)
async def listar_eventos(
    session_id: str, runtime: AdkRuntime = Depends(get_runtime)
) -> list[dict[str, Any]]:
    """Eventos ADK persistidos, integrais (``Event.model_dump(mode="json")``)."""
    return await runtime.get_events(session_id)
