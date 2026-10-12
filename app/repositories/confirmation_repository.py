"""Persistência de confirmações. Somente primitivas; sem regras do ADK nem de negócio.

Toda transição é um ``UPDATE`` condicional ao status de origem (e à sessão): quem
obtém ``rowcount == 1`` adquiriu a transição. Nunca ``SELECT`` seguido de ``UPDATE``.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Confirmacao
from app.domain.types import ConfirmationRecord, ConfirmationStatus


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(tzinfo=None)


def to_record(row: Confirmacao) -> ConfirmationRecord:
    return ConfirmationRecord(
        id=row.id,
        session_id=row.session_id,
        invocation_id=row.invocation_id,
        agent_name=row.agent_name,
        action=row.acao,
        details=json.loads(row.detalhes_json),
        status=ConfirmationStatus(row.status),
        created_at=row.created_at,
        responded_at=row.responded_at,
    )


class ConfirmationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert_pending(
        self,
        *,
        id: str,
        session_id: str,
        invocation_id: str,
        agent_name: str,
        action: str,
        details: dict[str, Any],
    ) -> bool:
        """Insere PENDING; ``False`` se o ID já existe (não sobrescreve nada)."""
        stmt = (
            sqlite_insert(Confirmacao)
            .values(
                id=id,
                session_id=session_id,
                invocation_id=invocation_id,
                agent_name=agent_name,
                acao=action,
                detalhes_json=json.dumps(details, sort_keys=True, ensure_ascii=False),
                status=ConfirmationStatus.PENDING.value,
                created_at=_utcnow(),
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )
        result = await self._session.execute(stmt)
        return result.rowcount == 1

    async def get(self, id: str, session_id: str) -> ConfirmationRecord | None:
        """Busca sempre restrita à sessão: ID de outra sessão equivale a inexistente."""
        row = await self._session.scalar(
            select(Confirmacao).where(Confirmacao.id == id, Confirmacao.session_id == session_id)
        )
        return to_record(row) if row is not None else None

    async def list_by_session(
        self, session_id: str, status: ConfirmationStatus | None = None
    ) -> list[ConfirmationRecord]:
        stmt = select(Confirmacao).where(Confirmacao.session_id == session_id)
        if status is not None:
            stmt = stmt.where(Confirmacao.status == status.value)
        rows = await self._session.scalars(stmt.order_by(Confirmacao.created_at, Confirmacao.id))
        return [to_record(r) for r in rows]

    async def _transition(
        self,
        id: str,
        session_id: str,
        *,
        source: ConfirmationStatus,
        target: ConfirmationStatus,
        responded: bool = False,
    ) -> bool:
        values: dict[str, Any] = {"status": target.value}
        if responded:
            values["responded_at"] = _utcnow()
        result = await self._session.execute(
            update(Confirmacao)
            .where(
                Confirmacao.id == id,
                Confirmacao.session_id == session_id,
                Confirmacao.status == source.value,
            )
            .values(**values)
        )
        return result.rowcount == 1

    async def claim(self, id: str, session_id: str) -> bool:
        """PENDING -> PROCESSING atômico (id AND session_id AND status=PENDING)."""
        return await self._transition(
            id,
            session_id,
            source=ConfirmationStatus.PENDING,
            target=ConfirmationStatus.PROCESSING,
        )

    async def finish(self, id: str, session_id: str, target: ConfirmationStatus) -> bool:
        """PROCESSING -> APPROVED | REJECTED."""
        if target not in (ConfirmationStatus.APPROVED, ConfirmationStatus.REJECTED):
            raise ValueError("estado final inválido")
        return await self._transition(
            id,
            session_id,
            source=ConfirmationStatus.PROCESSING,
            target=target,
            responded=True,
        )

    async def release(self, id: str, session_id: str) -> bool:
        """PROCESSING -> PENDING (somente quando nada foi executado)."""
        return await self._transition(
            id,
            session_id,
            source=ConfirmationStatus.PROCESSING,
            target=ConfirmationStatus.PENDING,
        )
