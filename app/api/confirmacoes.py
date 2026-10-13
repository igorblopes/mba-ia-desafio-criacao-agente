"""Resposta formal a confirmações. A validação PENDING/sessão e o claim ficam no runtime."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import get_runtime
from app.api.schemas import ConversationResponse, ErrorResponse, RespondConfirmationRequest
from app.runtime.adk_runtime import AdkRuntime

router = APIRouter(tags=["confirmacoes"])


@router.post(
    "/sessoes/{session_id}/confirmacoes",
    response_model=ConversationResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def responder_confirmacao(
    session_id: str,
    body: RespondConfirmationRequest,
    runtime: AdkRuntime = Depends(get_runtime),
) -> ConversationResponse:
    # 404 sessão inexistente; 409 confirmação inexistente / de outra sessão / não PENDING.
    result = await runtime.resume_confirmation(session_id, body.id, body.confirmado)
    pending = await runtime.list_pending_confirmations(session_id)
    return ConversationResponse.build(result.reply, pending)
