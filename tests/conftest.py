"""Fixtures: cada teste usa um SQLite temporário recriado a partir de ``dados/``.

Nunca toca em ``data/condominio.db`` nem escreve em ``dados/``.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from app.database.connection import create_domain_engine, create_session_factory
from scripts.reset import reset_domain


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    url = f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}"
    await reset_domain(url)
    engine = create_domain_engine(url)
    try:
        yield create_session_factory(engine)
    finally:
        await engine.dispose()


@pytest.fixture
def tools_wired(session_factory):
    """Aponta os Services usados pelas Tools para o banco temporário do teste."""
    from app.services.provider import configure_services, reset_services

    configure_services(session_factory)
    yield session_factory
    reset_services()


@pytest_asyncio.fixture
async def adk_runtime(session_factory, tmp_path):
    """AdkRuntime real (DatabaseSessionService em arquivo + LLM roteirizado, sem rede)."""
    from app.runtime.adk_runtime import build_adk_runtime
    from app.services.provider import reset_services
    from tests.fake_llm import ScriptedLlm
    from tests.scripted_plan import plan

    runtime = build_adk_runtime(
        domain_session_factory=session_factory,
        session_db_url=f"sqlite+aiosqlite:///{(tmp_path / 'adk_sessions.db').as_posix()}",
        llm=ScriptedLlm(plan=plan),
    )
    try:
        yield runtime
    finally:
        await runtime.close()
        reset_services()


@pytest_asyncio.fixture
async def world(session_factory, tmp_path):
    """Registrada na raiz para seleções que intercalam arquivos de vários diretórios."""
    import httpx
    from app.main import create_app
    from tests.adversarial.conftest import World
    from app.runtime.adk_runtime import build_adk_runtime
    from tests.adversarial.hostile_plan import plan
    from tests.fake_llm import ScriptedLlm

    url = f"sqlite+aiosqlite:///{(tmp_path / 'adk_sessions.db').as_posix()}"

    def factory():
        return build_adk_runtime(
            domain_session_factory=session_factory, session_db_url=url, llm=ScriptedLlm(plan=plan))

    app = create_app(factory)
    async with app.router.lifespan_context(app):
        # raise_app_exceptions=False: um 500 aparece como resposta (evidência), não como exceção.
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=120) as c:
            yield World(c, session_factory, app)
