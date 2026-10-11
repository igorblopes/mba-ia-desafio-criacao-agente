"""Engine e sessões assíncronas do banco de domínio (``condominio.db``).

Configuração SQLite aplicada a TODA conexão:

* ``foreign_keys=ON``  – o SQLite não impõe FKs por padrão.
* ``journal_mode=WAL`` – leitores não bloqueiam o escritor (melhor concorrência).
* ``busy_timeout``     – espera até N ms por um lock antes de falhar com
  "database is locked". Ajuda apenas em contenção TEMPORÁRIA.

Atenção: a garantia de unicidade de reserva (uma ATIVA por área/data) vem do
índice único parcial no banco, NÃO do timeout nem do WAL.
"""

from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

BUSY_TIMEOUT_MS = 5000


def create_domain_engine(url: str | None = None) -> AsyncEngine:
    engine = create_async_engine(url or get_settings().domain_database_url)

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _record) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        finally:
            cursor.close()

    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_domain_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = create_session_factory(get_engine())
    return _session_factory


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
