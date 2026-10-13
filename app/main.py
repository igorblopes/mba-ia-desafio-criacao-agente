"""Aplicação FastAPI: cria o app, o lifespan, os routers e os handlers. Sem regra de domínio.

    uv run uvicorn app.main:app --host 127.0.0.1 --port 8000

O startup NUNCA reseta dados; se o banco de domínio não foi inicializado, falha com instrução
explícita para rodar ``uv run python -m scripts.reset``.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import confirmacoes, sessoes, verificacao
from app.api.errors import register_exception_handlers
from app.runtime.adk_runtime import AdkRuntime, build_adk_runtime

logger = logging.getLogger("aurora.api")

RuntimeFactory = Callable[[], AdkRuntime]


def create_app(runtime_factory: RuntimeFactory = build_adk_runtime) -> FastAPI:
    """``runtime_factory`` existe para testes (LLM roteirizado, bancos temporários)."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        from app.database.connection import dispose_engine
        from app.services.provider import get_apartment_service, reset_services

        runtime = runtime_factory()  # um único runtime por processo (configura os Services)
        try:
            if not await get_apartment_service().is_initialized():
                raise RuntimeError(
                    "Banco de domínio não inicializado. Execute: uv run python -m scripts.reset"
                )
            app.state.adk_runtime = runtime
            yield
        finally:
            await runtime.close()
            await dispose_engine()
            reset_services()

    app = FastAPI(title="Residencial Aurora", lifespan=lifespan)
    register_exception_handlers(app)
    app.include_router(sessoes.router)
    app.include_router(confirmacoes.router)
    app.include_router(verificacao.router)
    return app


app = create_app()
