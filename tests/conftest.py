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
