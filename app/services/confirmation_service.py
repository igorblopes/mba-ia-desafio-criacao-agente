"""Ciclo de vida da confirmação (estado público). Independente de ADK e de HTTP.

PENDING --claim--> PROCESSING --> APPROVED | REJECTED
                        \--release (somente se nada executou)--> PENDING

Sem dependência de ADK: quem fala com o Runner é o ``AdkRuntime``.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import ConfirmationError, ConfirmationNotPendingError
from app.domain.types import ConfirmationRecord, ConfirmationStatus
from app.repositories.confirmation_repository import ConfirmationRepository
from app.services._persistence import service_session

logger = logging.getLogger("aurora.confirmation")


def _log(event: str, **ids: str) -> None:
    logger.info("%s %s", event, " ".join(f"{k}={v}" for k, v in ids.items()))


class ConfirmationService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory

    async def create_pending(
        self,
        *,
        id: str,
        session_id: str,
        invocation_id: str,
        agent_name: str,
        action: str,
        details: dict[str, Any],
    ) -> bool:
        """Registra PENDING. Idempotente por ID: repetir não duplica nem altera."""
        async with service_session(self._factory) as session:
            try:
                created = await ConfirmationRepository(session).insert_pending(
                    id=id,
                    session_id=session_id,
                    invocation_id=invocation_id,
                    agent_name=agent_name,
                    action=action,
                    details=details,
                )
                await session.commit()
            except BaseException:
                await session.rollback()
                raise
        if created:
            _log(
                "confirmation_created",
                session_id=session_id,
                confirmation_id=id,
                invocation_id=invocation_id,
                agent_name=agent_name,
            )
        return created

    async def get_for_session(self, id: str, session_id: str) -> ConfirmationRecord | None:
        async with service_session(self._factory) as session:
            return await ConfirmationRepository(session).get(id, session_id)

    async def list_pending_for_session(self, session_id: str) -> list[ConfirmationRecord]:
        async with service_session(self._factory) as session:
            return await ConfirmationRepository(session).list_by_session(
                session_id, ConfirmationStatus.PENDING
            )

    async def list_for_session(self, session_id: str) -> list[ConfirmationRecord]:
        async with service_session(self._factory) as session:
            return await ConfirmationRepository(session).list_by_session(session_id)

    async def claim_pending(self, id: str, session_id: str) -> ConfirmationRecord:
        """Adquire o direito de responder: UPDATE condicional, ``rowcount == 1``.

        Inexistente, de outra sessão ou não-PENDING falham igual (resposta neutra).
        """
        async with service_session(self._factory) as session:
            repo = ConfirmationRepository(session)
            try:
                claimed = await repo.claim(id, session_id)
                await session.commit()
            except BaseException:
                await session.rollback()
                raise
            if not claimed:
                raise ConfirmationNotPendingError()
            record = await repo.get(id, session_id)
        assert record is not None
        _log(
            "confirmation_claimed",
            session_id=session_id,
            confirmation_id=id,
            invocation_id=record.invocation_id,
            agent_name=record.agent_name,
        )
        return record

    async def _finish(
        self, record: ConfirmationRecord, target: ConfirmationStatus, event: str
    ) -> None:
        async with service_session(self._factory) as session:
            try:
                done = await ConfirmationRepository(session).finish(
                    record.id, record.session_id, target
                )
                await session.commit()
            except BaseException:
                await session.rollback()
                raise
        if not done:
            raise ConfirmationError("Confirmação não está em processamento.")
        _log(
            event,
            session_id=record.session_id,
            confirmation_id=record.id,
            invocation_id=record.invocation_id,
            agent_name=record.agent_name,
        )

    async def mark_approved(self, record: ConfirmationRecord) -> None:
        await self._finish(record, ConfirmationStatus.APPROVED, "confirmation_approved")

    async def mark_rejected(self, record: ConfirmationRecord) -> None:
        await self._finish(record, ConfirmationStatus.REJECTED, "confirmation_rejected")

    async def release_processing(self, record: ConfirmationRecord) -> bool:
        """PROCESSING -> PENDING. Só chamar quando é certo que nada foi executado."""
        async with service_session(self._factory) as session:
            try:
                released = await ConfirmationRepository(session).release(
                    record.id, record.session_id
                )
                await session.commit()
            except BaseException:
                await session.rollback()
                raise
        return released
