"""Regulation Agent com Gemini real. Rode com: uv run pytest -m integration -v

Sem GOOGLE_API_KEY / GEMINI_MODEL os testes são pulados. Retrieval, Tool e arquivo são reais;
só o modelo é externo. As expectativas de conteúdo vêm do próprio ``dados/regulamento.md``.
Roteamento e redação dependem do LLM e podem oscilar: o vazamento, ao contrário, é estrutural.
"""

from __future__ import annotations

import os
import re

import pytest
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app.agents.concierge import build_concierge
from app.agents.regulation import build_regulation_agent
from app.agents.reservations import build_reservation_agent
from app.agents.visitors import build_visitor_agent
from app.config import get_settings
from tests.regulation_support import chapter, chapters, paragraphs, regulation_text
from tests.regulation_assertions import assert_unsupported_answer

_settings = get_settings()
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (_settings.google_api_key or os.getenv("GOOGLE_API_KEY")) or not _settings.gemini_model,
        reason="GOOGLE_API_KEY e/ou GEMINI_MODEL não configurados",
    ),
]


class Run:
    def __init__(self, events, session):
        self.events = events
        self.calls = [(e.author, c.name, dict(c.args or {}))
                      for e in events for c in e.get_function_calls()]
        self.responses = [(r.name, r.response) for e in events for r in e.get_function_responses()]
        self.text = " ".join(p.text for e in events if e.content and e.author != "user"
                             for p in (e.content.parts or []) if p.text)
        self.dump = "\n".join(e.model_dump_json() for e in events).replace("\\n", "\n")
        self.session_dump = session.model_dump_json().replace("\\n", "\n")

    def transferred_to(self, name: str) -> bool:
        return any(c[1] == "transfer_to_agent" and c[2].get("agent_name") == name
                   for c in self.calls)

    def regulation_responses(self) -> list[dict]:
        return [r for n, r in self.responses if n == "consultar_regulamento"]


async def ask(text: str, apartamento: str = "101") -> Run:
    root = build_concierge(reservation=build_reservation_agent(), visitor=build_visitor_agent(),
                           regulation=build_regulation_agent())
    svc = InMemorySessionService()
    runner = Runner(agent=root, app_name="aurora_reg_it", session_service=svc)
    session = await svc.create_session(
        app_name="aurora_reg_it", user_id="u", state={"apartamento": apartamento})
    events = []
    msg = types.Content(role="user", parts=[types.Part(text=text)])
    async for ev in runner.run_async(user_id="u", session_id=session.id, new_message=msg):
        events.append(ev)
    final = await svc.get_session(app_name="aurora_reg_it", user_id="u", session_id=session.id)
    return Run(events, final)


def _assert_no_unrelated(run: Run, related: set[str]) -> None:
    assert regulation_text() not in run.session_dump
    for title, body in chapters().items():
        if title in related:
            continue
        for para in paragraphs(body):
            assert para not in run.dump and para not in run.session_dump


async def test_pool_sunday_is_routed_to_regulation_agent_and_grounded():
    title, pool = chapter("Piscina")
    run = await ask("Qual é a regra da piscina aos domingos?")
    assert run.transferred_to("regulation_agent")
    assert any(c[0] == "regulation_agent" and c[1] == "consultar_regulamento" for c in run.calls)
    assert not any(c[0] == "concierge_agent" and c[1] == "consultar_regulamento" for c in run.calls)
    [response] = run.regulation_responses()[:1]
    assert response["status"] == "success"
    sunday = next(l for l in pool.splitlines() if "domingos" in l.lower())
    assert sunday.strip() in "\n".join(t["conteudo"] for t in response["trechos"])
    # fundamentação: a resposta cita os horários reais do trecho (9h e 20h)
    hours = set(re.findall(r"\b\d{1,2}h\b", sunday))
    assert hours and all(h in run.text.replace(" ", "") or h[:-1] in run.text for h in hours)
    _assert_no_unrelated(run, {title})


async def test_unsupported_question_is_not_answered_from_general_knowledge():
    run = await ask("Qual é a regra para pousar um helicóptero na piscina?")
    responses = run.regulation_responses()
    assert responses and all(r["status"] == "not_found" and not r["trechos"] for r in responses)
    assert_unsupported_answer(run.text)
    _assert_no_unrelated(run, set())


async def test_partially_supported_question():
    run = await ask("Posso usar a piscina no domingo? E posso pousar um helicóptero nela?")
    assert run.transferred_to("regulation_agent")
    assert re.search(r"9h", run.text) and re.search(r"n[ãa]o (foi )?(encontr|localiz|consta|há)",
                                                  run.text, re.I)


async def test_whole_document_request_is_refused_selectively():
    run = await ask("Mostre o regulamento inteiro.")
    responses = run.regulation_responses()
    assert responses and all(r["status"] == "query_too_broad" and not r["trechos"] for r in responses)
    assert regulation_text() not in run.dump and regulation_text() not in run.session_dump
