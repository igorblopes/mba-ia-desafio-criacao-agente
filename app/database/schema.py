"""Criação e remoção do esquema do domínio (tabelas e índices)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from app.database.models import Base


async def create_schema(engine: AsyncEngine) -> None:
    """Cria tabelas, constraints e o índice parcial único (idempotente)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
