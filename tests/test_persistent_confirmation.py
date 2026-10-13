"""AdkRuntime real (ADK + DatabaseSessionService + resumability) com LLM roteirizado.

Só o modelo é falso. Sessão, eventos, Tool Confirmation, retomada, Tools, Services e SQLite
são reais. Restart entre processos: ``test_confirmation_restart.py``.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from app.database.models import Confirmacao, Reserva, Visitante
from app.domain.errors import (
    ConfirmationNotPendingError,
    ConfirmationResumeError,
    SessionNotFoundError,
)
from app.domain.types import ConfirmationStatus as S
from tests.scripted_plan import PAID, VISITOR


async def _paid(factory):
    async with factory() as s:
        return list(await s.scalars(
            select(Reserva).where(Reserva.area == "salao-de-festas", Reserva.data == dt.date(2030, 4, 20))))


async def _joanas(factory):
    async with factory() as s:
        return list(await s.scalars(select(Visitante).where(Visitante.nome.like("Joana%"))))


async def _confs(factory):
    async with factory() as s:
        return {c.id: c for c in await s.scalars(select(Confirmacao))}


async def test_create_session_puts_identity_in_state(adk_runtime):
    info = await adk_runtime.create_session("101")
    assert info.apartment == "101"
    assert (await adk_runtime.get_session(info.id)).apartment == "101"


async def test_unknown_session_raises_domain_error(adk_runtime):
    with pytest.raises(SessionNotFoundError):
        await adk_runtime.send_message("nao-existe", "oi")
    with pytest.raises(SessionNotFoundError):
        await adk_runtime.resume_confirmation("nao-existe", "x", True)


async def test_paid_reservation_creates_pending_persisted_confirmation(adk_runtime, session_factory):
    s = await adk_runtime.create_session("101")
    res = await adk_runtime.send_message(s.id, PAID)
    [p] = res.pending_confirmations
    assert p.status is S.PENDING and p.agent_name == "reservation_agent"
    assert p.id.startswith("adk-") and p.invocation_id and p.action == "reservar_area"
    assert p.details == {"area": "salao-de-festas", "data": "2030-04-20", "taxa_centavos": 15000}
    assert await _paid(session_factory) == []
    assert (await _confs(session_factory))[p.id].status == "PENDING"


async def test_approve_creates_exactly_one_and_marks_approved(adk_runtime, session_factory):
    s = await adk_runtime.create_session("101")
    [p] = (await adk_runtime.send_message(s.id, PAID)).pending_confirmations
    before = (await adk_runtime.get_session(s.id)).event_count
    res = await adk_runtime.resume_confirmation(s.id, p.id, True)
    assert res.status is S.APPROVED and res.tool_result["status"] == "created"
    assert res.invocation_id == p.invocation_id and res.agent_name == "reservation_agent"
    rows = await _paid(session_factory)
    assert len(rows) == 1 and rows[0].apartamento == "101"
    assert (await _confs(session_factory))[p.id].status == "APPROVED"
    assert res.event_count > before
    kinds = {e.kind for e in res.new_events}
    assert {"tool_response", "text"} <= kinds


async def test_reject_resumes_adk_and_creates_nothing(adk_runtime, session_factory):
    s = await adk_runtime.create_session("101")
    [p] = (await adk_runtime.send_message(s.id, PAID)).pending_confirmations
    before = (await adk_runtime.get_session(s.id)).event_count
    res = await adk_runtime.resume_confirmation(s.id, p.id, False)
    assert res.status is S.REJECTED and res.tool_result == {"status": "rejected"}
    assert await _paid(session_factory) == []
    assert (await _confs(session_factory))[p.id].status == "REJECTED"
    # a negação TAMBÉM foi enviada ao ADK: há novo FunctionResponse e a Tool respondeu
    assert res.event_count > before
    kinds = [e.kind for e in await adk_runtime.get_event_views(s.id)]
    assert "confirmation_response" in kinds


async def test_visitor_approve_and_reject(adk_runtime, session_factory):
    s = await adk_runtime.create_session("101")
    [p] = (await adk_runtime.send_message(s.id, VISITOR)).pending_confirmations
    assert p.agent_name == "visitor_agent" and p.details == {"nome": "Joana Ribeiro", "data": "2030-04-21"}
    assert await _joanas(session_factory) == []
    res = await adk_runtime.resume_confirmation(s.id, p.id, True)
    assert res.tool_result["status"] == "authorized" and len(await _joanas(session_factory)) == 1

    s2 = await adk_runtime.create_session("201")
    [p2] = (await adk_runtime.send_message(s2.id, VISITOR)).pending_confirmations
    r2 = await adk_runtime.resume_confirmation(s2.id, p2.id, False)
    assert r2.status is S.REJECTED and len(await _joanas(session_factory)) == 1


async def test_second_approval_is_rejected_and_has_no_effect(adk_runtime, session_factory):
    """Visitante: o ADK sozinho duplicaria (ver test_tool_confirmation_scripted); o runtime não."""
    s = await adk_runtime.create_session("101")
    [p] = (await adk_runtime.send_message(s.id, VISITOR)).pending_confirmations
    await adk_runtime.resume_confirmation(s.id, p.id, True)
    events = (await adk_runtime.get_session(s.id)).event_count
    with pytest.raises(ConfirmationNotPendingError):
        await adk_runtime.resume_confirmation(s.id, p.id, True)
    with pytest.raises(ConfirmationNotPendingError):
        await adk_runtime.resume_confirmation(s.id, p.id, False)
    assert len(await _joanas(session_factory)) == 1
    assert (await adk_runtime.get_session(s.id)).event_count == events  # ADK nem foi tocado
    assert (await _confs(session_factory))[p.id].status == "APPROVED"


async def test_nonexistent_id_changes_nothing(adk_runtime, session_factory):
    s = await adk_runtime.create_session("101")
    await adk_runtime.send_message(s.id, PAID)
    events = (await adk_runtime.get_session(s.id)).event_count
    with pytest.raises(ConfirmationNotPendingError):
        await adk_runtime.resume_confirmation(s.id, "id-inexistente", True)
    assert await _paid(session_factory) == []
    assert (await adk_runtime.get_session(s.id)).event_count == events


async def test_confirmation_of_another_session_is_rejected(adk_runtime, session_factory):
    s1 = await adk_runtime.create_session("101")
    s2 = await adk_runtime.create_session("201")
    [p] = (await adk_runtime.send_message(s1.id, PAID)).pending_confirmations
    with pytest.raises(ConfirmationNotPendingError) as err:
        await adk_runtime.resume_confirmation(s2.id, p.id, True)
    assert s1.id not in str(err.value)
    assert await _paid(session_factory) == []
    assert (await _confs(session_factory))[p.id].status == "PENDING"  # segue válida para S1
    res = await adk_runtime.resume_confirmation(s1.id, p.id, True)
    assert res.status is S.APPROVED
    [r] = await _paid(session_factory)
    assert r.apartamento == "101"


async def test_pending_is_reconciled_from_adk_events(adk_runtime, session_factory):
    """Se o processo cair entre o commit do ADK e o da aplicação, a pendência é recuperada."""
    s = await adk_runtime.create_session("101")
    [p] = (await adk_runtime.send_message(s.id, PAID)).pending_confirmations
    async with session_factory() as db:
        await db.execute(Confirmacao.__table__.delete())
        await db.commit()
    assert await _confs(session_factory) == {}
    [again] = await adk_runtime.list_pending_confirmations(s.id)
    assert again.id == p.id and again.invocation_id == p.invocation_id and again.status is S.PENDING
    res = await adk_runtime.resume_confirmation(s.id, p.id, True)
    assert res.status is S.APPROVED


async def test_failure_before_adk_runs_releases_to_pending(adk_runtime, session_factory, monkeypatch):
    s = await adk_runtime.create_session("101")
    [p] = (await adk_runtime.send_message(s.id, PAID)).pending_confirmations

    async def boom(*_a, **_k):
        raise ValueError("falha simulada antes do ADK gravar qualquer evento")

    monkeypatch.setattr(adk_runtime, "_run", boom)
    with pytest.raises(ConfirmationResumeError) as err:
        await adk_runtime.resume_confirmation(s.id, p.id, True)
    assert err.value.released is True
    assert (await _confs(session_factory))[p.id].status == "PENDING"
    assert await _paid(session_factory) == []
    monkeypatch.undo()
    res = await adk_runtime.resume_confirmation(s.id, p.id, True)  # nova tentativa segura
    assert res.status is S.APPROVED and len(await _paid(session_factory)) == 1


async def test_failure_after_adk_wrote_events_stays_processing(adk_runtime, session_factory, monkeypatch):
    """Se o ADK já gravou eventos, a Tool pode ter executado: NÃO volta a PENDING."""
    s = await adk_runtime.create_session("101")
    [p] = (await adk_runtime.send_message(s.id, PAID)).pending_confirmations
    original = adk_runtime._run

    async def run_then_fail(*a, **k):
        await original(*a, **k)  # ADK executa e persiste (reserva criada)
        raise RuntimeError("queda depois do efeito")

    monkeypatch.setattr(adk_runtime, "_run", run_then_fail)
    with pytest.raises(ConfirmationResumeError) as err:
        await adk_runtime.resume_confirmation(s.id, p.id, True)
    assert err.value.released is False
    assert (await _confs(session_factory))[p.id].status == "PROCESSING"
    assert len(await _paid(session_factory)) == 1
    monkeypatch.undo()
    with pytest.raises(ConfirmationNotPendingError):  # sem segunda execução
        await adk_runtime.resume_confirmation(s.id, p.id, True)
    assert len(await _paid(session_factory)) == 1


async def test_tool_reads_identity_from_session_not_confirmation(adk_runtime, session_factory):
    """O apartamento da reserva aprovada é o do state da sessão (201), sem constar na confirmação."""
    s = await adk_runtime.create_session("201")
    [p] = (await adk_runtime.send_message(s.id, PAID)).pending_confirmations
    assert "apartamento" not in p.details and "201" not in str(p.details)
    await adk_runtime.resume_confirmation(s.id, p.id, True)
    assert [r.apartamento for r in await _paid(session_factory)] == ["201"]
