"""Fixtures: cada teste usa um SQLite temporário recriado a partir de ``dados/``.

Nunca toca em ``data/condominio.db`` nem escreve em ``dados/``.
"""

from __future__ import annotations

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
