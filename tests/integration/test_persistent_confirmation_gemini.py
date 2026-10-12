"""Confirmação persistente com Gemini REAL. Rode com: uv run pytest -m integration -v

Pulado sem GOOGLE_API_KEY / GEMINI_MODEL (a ausência NÃO conta como validação). A mecânica
de restart está provada com LLM roteirizado em ``tests/test_confirmation_restart.py``.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.database.models import Reserva
from app.runtime.adk_runtime import build_adk_runtime
from tests.scripted_plan import PAID

_settings = get_settings()
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (_settings.google_api_key or os.getenv("GOOGLE_API_KEY")) or not _settings.gemini_model,
        reason="GOOGLE_API_KEY e/ou GEMINI_MODEL não configurados",
    ),
]


async def test_gemini_pending_survives_new_runtime_and_approves_once(session_factory, tmp_path):
    url = f"sqlite+aiosqlite:///{(tmp_path / 'adk_sessions.db').as_posix()}"
    first = build_adk_runtime(domain_session_factory=session_factory, session_db_url=url)
    s = await first.create_session("101")
    [p] = (await first.send_message(s.id, PAID)).pending_confirmations
    await first.close()

    second = build_adk_runtime(domain_session_factory=session_factory, session_db_url=url)
    try:
        assert (await second.get_session(s.id)).apartment == "101"
        res = await second.resume_confirmation(s.id, p.id, True)
        assert res.tool_result["status"] == "created"
    finally:
        await second.close()
    async with session_factory() as db:
        rows = [r for r in await db.scalars(select(Reserva)) if r.data.isoformat() == "2030-04-20"
                and r.area == "salao-de-festas"]
    assert len(rows) == 1
