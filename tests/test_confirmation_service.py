"""Repository/Service de confirmações: máquina de estados, claim atômico e isolamento.

Offline: sem Gemini, sem ADK.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import inspect, select, text

from app.database.models import Confirmacao
from app.domain.errors import ConfirmationError, ConfirmationNotPendingError
from app.domain.types import ConfirmationStatus as S
from app.services.confirmation_service import ConfirmationService

DETAILS = {"area": "salao-de-festas", "data": "2030-04-20", "taxa_centavos": 15000}


@pytest.fixture
def service(session_factory):
    return ConfirmationService(session_factory)


async def _create(service, id="adk-abc", session_id="S1", **kw):
    return await service.create_pending(
        id=id, session_id=session_id, invocation_id=kw.get("invocation_id", "e-1"),
        agent_name=kw.get("agent_name", "reservation_agent"), action="reservar_area",
        details=kw.get("details", DETAILS),
    )


async def test_create_pending_persists_all_fields(service):
    assert await _create(service) is True
    rec = await service.get_for_session("adk-abc", "S1")
    assert rec.status is S.PENDING
    assert (rec.id, rec.session_id, rec.invocation_id, rec.agent_name, rec.action) == (
        "adk-abc", "S1", "e-1", "reservation_agent", "reservar_area")
    assert rec.details == DETAILS and rec.created_at and rec.responded_at is None


async def test_create_pending_is_idempotent_and_does_not_overwrite(service):
    assert await _create(service) is True
    await service.claim_pending("adk-abc", "S1")
    assert await _create(service, details={"x": 1}) is False  # mesmo ID: ignorado
    rec = await service.get_for_session("adk-abc", "S1")
    assert rec.status is S.PROCESSING and rec.details == DETAILS


async def test_table_has_no_apartment_or_secrets(session_factory):
    async with session_factory() as s:
        cols = await s.run_sync(lambda sync: [c["name"] for c in inspect(sync.bind).get_columns("confirmacoes")])
    assert cols == ["id", "session_id", "invocation_id", "agent_name", "acao",
                    "detalhes_json", "status", "created_at", "responded_at"]


async def test_status_check_constraint(session_factory):
    async with session_factory() as s:
        with pytest.raises(Exception, match="(?i)constraint"):
            await s.execute(text(
                "INSERT INTO confirmacoes VALUES ('x','S','i','a','b','{}','BOGUS',"
                "'2030-01-01 00:00:00', NULL)"))


async def test_full_cycle_approved_and_rejected(service):
    await _create(service, id="a")
    await _create(service, id="b")
    ra = await service.claim_pending("a", "S1")
    assert ra.status is S.PROCESSING
    await service.mark_approved(ra)
    rb = await service.claim_pending("b", "S1")
    await service.mark_rejected(rb)
    assert (await service.get_for_session("a", "S1")).status is S.APPROVED
    done = await service.get_for_session("b", "S1")
    assert done.status is S.REJECTED and done.responded_at is not None
    assert await service.list_pending_for_session("S1") == []


async def test_nonexistent_id_is_rejected(service):
    with pytest.raises(ConfirmationNotPendingError):
        await service.claim_pending("id-inexistente", "S1")


async def test_other_session_is_rejected_neutrally_and_untouched(service):
    await _create(service, id="abc", session_id="S1")
    with pytest.raises(ConfirmationNotPendingError) as err:
        await service.claim_pending("abc", "S2")
    assert "S1" not in str(err.value)
    assert (await service.get_for_session("abc", "S1")).status is S.PENDING
    assert await service.get_for_session("abc", "S2") is None


async def test_answered_id_cannot_be_claimed_again(service):
    await _create(service, id="abc")
    await service.mark_approved(await service.claim_pending("abc", "S1"))
    with pytest.raises(ConfirmationNotPendingError):
        await service.claim_pending("abc", "S1")
    assert (await service.get_for_session("abc", "S1")).status is S.APPROVED


async def test_processing_cannot_be_claimed_again(service):
    await _create(service, id="abc")
    await service.claim_pending("abc", "S1")
    with pytest.raises(ConfirmationNotPendingError):
        await service.claim_pending("abc", "S1")


async def test_claim_is_atomic_under_concurrency(service):
    await _create(service, id="abc")
    results = await asyncio.gather(
        *(service.claim_pending("abc", "S1") for _ in range(12)), return_exceptions=True
    )
    wins = [r for r in results if not isinstance(r, Exception)]
    losses = [r for r in results if isinstance(r, ConfirmationNotPendingError)]
    assert len(wins) == 1 and len(losses) == 11


async def test_finish_requires_processing(service):
    await _create(service, id="abc")
    rec = await service.get_for_session("abc", "S1")  # ainda PENDING
    with pytest.raises(ConfirmationError):
        await service.mark_approved(rec)
    assert (await service.get_for_session("abc", "S1")).status is S.PENDING


async def test_release_processing_returns_to_pending_and_allows_new_claim(service):
    await _create(service, id="abc")
    rec = await service.claim_pending("abc", "S1")
    assert await service.release_processing(rec) is True
    assert (await service.get_for_session("abc", "S1")).status is S.PENDING
    assert (await service.claim_pending("abc", "S1")).status is S.PROCESSING


async def test_release_does_not_touch_finished(service):
    await _create(service, id="abc")
    rec = await service.claim_pending("abc", "S1")
    await service.mark_approved(rec)
    assert await service.release_processing(rec) is False
    assert (await service.get_for_session("abc", "S1")).status is S.APPROVED


async def test_list_pending_is_scoped_by_session(service):
    await _create(service, id="a", session_id="S1")
    await _create(service, id="b", session_id="S2")
    assert [r.id for r in await service.list_pending_for_session("S1")] == ["a"]


async def test_details_json_is_plain_json(session_factory, service):
    await _create(service, id="a")
    async with session_factory() as s:
        row = (await s.scalars(select(Confirmacao))).one()
    assert row.detalhes_json == '{"area": "salao-de-festas", "data": "2030-04-20", "taxa_centavos": 15000}'
