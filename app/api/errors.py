"""Tradução de erros de domínio para HTTP. Mensagens vêm do próprio erro (já genéricas)."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.domain.errors import (
    AgentRunLimitError,
    ApartmentNotFoundError,
    ConfirmationNotPendingError,
    ConfirmationResumeError,
    DomainError,
    SessionNotFoundError,
    StorageBusyError,
)


def _handler(status_code: int):
    async def handle(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status_code, content={"detail": str(exc)})

    return handle


async def _resume_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ConfirmationResumeError)
    # released=True: nada executou e repetir é seguro (503). Caso contrário o resultado
    # precisa ser verificado; continua sendo falha técnica (500), nunca sucesso.
    return JSONResponse(status_code=503 if exc.released else 500, content={"detail": str(exc)})


async def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    """422 sem eco do input.

    O handler padrão do FastAPI devolve ``input`` (o valor recebido) e o serializa como JSON
    estrito: ``NaN``/``Infinity``/``1e999`` no corpo quebravam essa serialização e viravam HTTP 500
    (F-2). Aqui só saem tipo, local e mensagem; o valor do usuário nunca é refletido.
    """
    assert isinstance(exc, RequestValidationError)
    detail = [
        {"type": str(e.get("type", "")), "loc": [str(x) for x in e.get("loc", ())],
         "msg": str(e.get("msg", ""))}
        for e in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": detail})


def register_exception_handlers(app: FastAPI) -> None:
    """Ordem não importa: o Starlette escolhe a classe mais específica."""
    app.add_exception_handler(SessionNotFoundError, _handler(404))
    app.add_exception_handler(ApartmentNotFoundError, _handler(404))
    app.add_exception_handler(ConfirmationNotPendingError, _handler(409))
    app.add_exception_handler(ConfirmationResumeError, _resume_error)
    app.add_exception_handler(StorageBusyError, _handler(503))
    app.add_exception_handler(AgentRunLimitError, _handler(502))
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(DomainError, _handler(400))
    # Erros inesperados NÃO são mascarados: seguem como 500 do Starlette.
