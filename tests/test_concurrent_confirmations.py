"""Duas confirmações independentes aprovadas ao mesmo tempo para a mesma área/data."""

from __future__ import annotations

import asyncio
import datetime as dt

from sqlalchemy import select

from app.database.models import STATUS_ATIVA, Confirmacao, Reserva
from app.domain.types import ConfirmationStatus as S
from tests.scripted_plan import PAID_0511


async def test_two_sessions_approve_concurrently_one_reservation(adk_runtime, session_factory):
    s3 = await adk_runtime.create_session("101")
    s4 = await adk_runtime.create_session("201")
    [p3] = (await adk_runtime.send_message(s3.id, PAID_0511)).pending_confirmations
    [p4] = (await adk_runtime.send_message(s4.id, PAID_0511)).pending_confirmations
    assert p3.id != p4.id and p3.invocation_id != p4.invocation_id  # independentes
    assert p3.status is S.PENDING and p4.status is S.PENDING

    r3, r4 = await asyncio.gather(
        adk_runtime.resume_confirmation(s3.id, p3.id, True),
        adk_runtime.resume_confirmation(s4.id, p4.id, True),
    )

    # Ambas as respostas foram processadas, sem exceção nem sessão corrompida...
    assert r3.status is S.APPROVED and r4.status is S.APPROVED
    outcomes = sorted(r.tool_result["status"] for r in (r3, r4))
    assert outcomes == ["created", "unavailable"]  # conflito é retorno funcional normal
    # ...e há exatamente UMA reserva ativa para salão/2030-05-11.
    async with session_factory() as s:
        ativas = list(await s.scalars(select(Reserva).where(
            Reserva.area == "salao-de-festas", Reserva.data == dt.date(2030, 5, 11),
            Reserva.status == STATUS_ATIVA)))
        confs = {c.id: c.status for c in await s.scalars(select(Confirmacao))}
    assert len(ativas) == 1
    winner = r3 if r3.tool_result["status"] == "created" else r4
    assert ativas[0].apartamento == {s3.id: "101", s4.id: "201"}[winner.session_id]
    # APPROVED = resposta do usuário, mesmo para quem perdeu a disputa de negócio.
    assert confs == {p3.id: "APPROVED", p4.id: "APPROVED"}
    # Sessões íntegras: eventos legíveis e invocation concluída nas duas.
    for sid in (s3.id, s4.id):
        kinds = [e.kind for e in await adk_runtime.get_event_views(sid)]
        assert kinds[-1] == "text" and "confirmation_response" in kinds


async def test_same_confirmation_answered_concurrently_runs_once(adk_runtime, session_factory):
    s = await adk_runtime.create_session("101")
    [p] = (await adk_runtime.send_message(s.id, PAID_0511)).pending_confirmations
    results = await asyncio.gather(
        *(adk_runtime.resume_confirmation(s.id, p.id, True) for _ in range(6)),
        return_exceptions=True,
    )
    ok = [r for r in results if not isinstance(r, Exception)]
    assert len(ok) == 1 and ok[0].tool_result["status"] == "created"
    from app.domain.errors import ConfirmationNotPendingError
    assert all(isinstance(r, ConfirmationNotPendingError) for r in results if isinstance(r, Exception))
    async with session_factory() as db:
        rows = list(await db.scalars(select(Reserva).where(Reserva.data == dt.date(2030, 5, 11))))
    assert len([r for r in rows if r.status == STATUS_ATIVA]) == 1
