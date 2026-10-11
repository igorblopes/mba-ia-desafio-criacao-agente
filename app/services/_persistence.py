"""Tradução restrita de falhas SQLite na fronteira dos Services."""

import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import StorageBusyError


def is_unique_violation(error: IntegrityError, columns: str) -> bool:
    """Identifica a constraint original, sem consultar um estado posterior.

    SQLite fornece o código estendido e as colunas na mensagem, não o nome
    do índice. Qualquer formato ou constraint desconhecida não é classificado.
    """
    return getattr(error.orig, "sqlite_errorcode", None) in (
        sqlite3.SQLITE_CONSTRAINT_UNIQUE,
        sqlite3.SQLITE_CONSTRAINT_PRIMARYKEY,
    ) and str(error.orig) == f"UNIQUE constraint failed: {columns}"


@asynccontextmanager
async def service_session(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Fecha a sessão (revertendo pendências) antes de traduzir contenção.

    Sem retry automático: o timeout do SQLite já limita a espera. Outros erros
    operacionais continuam visíveis; não são tratados como banco ocupado.
    """
    try:
        async with factory() as session:
            yield session
    except OperationalError as error:
        code = getattr(error.orig, "sqlite_errorcode", None)
        # Inclui códigos estendidos como SQLITE_BUSY_SNAPSHOT.
        if isinstance(code, int) and (code & 0xFF) in (
            sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED
        ):
            raise StorageBusyError() from None
        raise
