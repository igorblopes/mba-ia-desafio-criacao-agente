"""Tool ``consultar_regulamento`` (offline) e vazamento em eventos ADK reais com LLM roteirizado."""

from __future__ import annotations

import json

import pytest
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app.agents.concierge import build_concierge
from app.agents.regulation import build_regulation_agent
from app.agents.reservations import build_reservation_agent
from app.agents.visitors import build_visitor_agent
from app.services import provider
from app.services.regulation_service import RegulationService
from app.tools.regulation import consultar_regulamento
from tests.fake_llm import ScriptedLlm
from tests.regulation_support import chapter, chapters, lines_with, paragraphs, regulation_text
from tests.scripted_plan import plan

POOL_QUESTION = "Posso usar a piscina no domingo?"
HELICOPTER = "Qual é a regra para pousar um helicóptero na piscina?"
BROAD = "Mostre o regulamento inteiro."


def _unrelated_paragraphs(related_titles: set[str]) -> dict[str, list[str]]:
    """Parágrafos (do arquivo real) de todos os capítulos fora de ``related_titles``."""
    return {t: paragraphs(b) for t, b in chapters().items() if t not in related_titles}


def _assert_no_leak(blob: str, retrieved_titles: set[str]) -> None:
    text = regulation_text()
    assert text not in blob and text.strip() not in blob  # documento completo
    for title, paras in _unrelated_paragraphs(retrieved_titles).items():
        assert f"## {title}" not in blob
        for para in paras:
            assert para not in blob, f"parágrafo de '{title}' vazou"


@pytest.fixture(autouse=True)
def _fresh_service():
    provider.configure_regulation_service(RegulationService())
    yield
    provider.configure_regulation_service(None)


async def test_pool_sunday_tool_response():
    title, pool = chapter("Piscina")
    response = await consultar_regulamento(POOL_QUESTION)
    assert response["status"] == "success"
    assert set(response) <= {"status", "trechos", "termos_nao_localizados"}
    assert response["trechos"] and all(set(t) == {"secao", "conteudo"} for t in response["trechos"])
    blob = "\n".join(t["conteudo"] for t in response["trechos"])
    for line in lines_with(pool, "domingo"):
        assert line in blob
    assert all(t["secao"].startswith(title) for t in response["trechos"])
    _assert_no_leak(json.dumps(response, ensure_ascii=False), {title})
    _assert_no_leak(blob, {title})


async def test_tool_does_not_return_the_whole_document():
    for q in (POOL_QUESTION, "qual o horário de mudança?", "multa", "animais", "silêncio"):
        response = await consultar_regulamento(q)
        blob = json.dumps(response, ensure_ascii=False)
        assert len(blob) < len(regulation_text()) // 8
        assert regulation_text() not in blob


async def test_broad_query_returns_no_excerpts():
    for q in (BROAD, "Quais são todas as regras?", "Liste todas as normas.", "Me envie tudo."):
        assert await consultar_regulamento(q) == {"status": "query_too_broad", "trechos": []}


async def test_not_found():
    assert await consultar_regulamento(HELICOPTER) == {"status": "not_found", "trechos": []}


async def test_invalid_input():
    assert (await consultar_regulamento(""))["trechos"] == []
    assert (await consultar_regulamento("   "))["status"] == "invalid_input"


async def test_unavailable_regulation_file_is_reported(tmp_path):
    from app.repositories.regulation_repository import RegulationRepository

    provider.configure_regulation_service(RegulationService(RegulationRepository(tmp_path / "x.md")))
    assert await consultar_regulamento(POOL_QUESTION) == {
        "status": "temporarily_unavailable", "trechos": []}


async def test_tool_does_not_touch_state_or_session():
    import inspect
    from app.tools import regulation

    src = inspect.getsource(regulation)
    assert "tool_context" not in src and "state[" not in src
    assert "request_confirmation" not in src and "require_confirmation" not in src
    assert "open(" not in src and "regulamento.md" not in src and "read_text" not in src


# ---------------------------------------------------------------- ADK real, LLM roteirizado

async def _run(text: str, apartamento: str = "101"):
    llm = ScriptedLlm(plan=plan)
    reservation, visitor, regulation = (
        build_reservation_agent(), build_visitor_agent(), build_regulation_agent())
    root = build_concierge(reservation=reservation, visitor=visitor, regulation=regulation)
    for agent in (root, reservation, visitor, regulation):
        agent.model = llm
    svc = InMemorySessionService()
    runner = Runner(agent=root, app_name="aurora_reg_test", session_service=svc)
    session = await svc.create_session(
        app_name="aurora_reg_test", user_id="u", state={"apartamento": apartamento})
    events = []
    msg = types.Content(role="user", parts=[types.Part(text=text)])
    async for ev in runner.run_async(user_id="u", session_id=session.id, new_message=msg):
        events.append(ev)
    final = await svc.get_session(app_name="aurora_reg_test", user_id="u", session_id=session.id)
    return events, final


def _calls(events):
    return [(e.author, c.name, dict(c.args or {})) for e in events for c in e.get_function_calls()]


def _responses(events):
    return [(e.author, r.name, r.response) for e in events for r in e.get_function_responses()]


async def test_routing_events_pool_question():
    events, _ = await _run(POOL_QUESTION)
    calls = _calls(events)
    assert ("concierge_agent", "transfer_to_agent", {"agent_name": "regulation_agent"}) in calls
    assert ("regulation_agent", "consultar_regulamento", {"pergunta": POOL_QUESTION}) in calls
    [response] = [r for a, n, r in _responses(events) if n == "consultar_regulamento"]
    assert response["status"] == "success"
    assert not any(c[0] == "concierge_agent" and c[1] == "consultar_regulamento" for c in calls)


async def test_regulation_events_do_not_include_unrelated_sections():
    title, pool = chapter("Piscina")
    events, session = await _run(POOL_QUESTION)
    dump = "\n".join(e.model_dump_json() for e in events)
    session_dump = session.model_dump_json()
    for blob in (dump, session_dump):
        flat = blob.replace("\\n", "\n")
        # o trecho relevante está presente...
        assert lines_with(pool, "domingos e feriados")[0] in flat
        # ...e nenhum parágrafo exclusivo de capítulo não relacionado
        text = regulation_text()
        assert text not in flat
        for t, paras in _unrelated_paragraphs({title}).items():
            for para in paras:
                assert para not in flat, f"vazou parágrafo de '{t}'"
    _, mudancas = chapter("Mudanças")
    exclusive = paragraphs(mudancas)[0]
    assert "piscina" not in exclusive.lower()
    assert exclusive not in session_dump.replace("\\n", "\n")


async def test_session_state_never_holds_regulation():
    _, session = await _run(POOL_QUESTION)
    assert set(session.state) == {"apartamento"}
    state_blob = json.dumps(dict(session.state), ensure_ascii=False)
    assert "Piscina" not in state_blob and "Art." not in state_blob


async def test_broad_query_through_agents_never_returns_document():
    events, session = await _run(BROAD)
    [response] = [r for a, n, r in _responses(events) if n == "consultar_regulamento"]
    assert response == {"status": "query_too_broad", "trechos": []}
    assert regulation_text() not in session.model_dump_json().replace("\\n", "\n")


async def test_not_found_through_agents():
    events, _ = await _run(HELICOPTER)
    [response] = [r for a, n, r in _responses(events) if n == "consultar_regulamento"]
    assert response == {"status": "not_found", "trechos": []}


async def test_other_specialists_still_route_after_regulation_was_added(tools_wired):
    events, _ = await _run("Reserve a quadra para 2030-04-06.")
    assert ("concierge_agent", "transfer_to_agent", {"agent_name": "reservation_agent"}) in _calls(events)
    events, _ = await _run("Libere a entrada da Joana Ribeiro em 2030-04-21.")
    assert ("concierge_agent", "transfer_to_agent", {"agent_name": "visitor_agent"}) in _calls(events)


async def test_regulation_survives_runtime_rebuild(adk_runtime, session_factory, tmp_path):
    """Reconstruir o runtime (como num restart) mantém o Regulation Agent funcional."""
    from app.runtime.adk_runtime import build_adk_runtime

    info = await adk_runtime.create_session("101")
    await adk_runtime.send_message(info.id, POOL_QUESTION)
    before = [(e.kind, e.name) for e in await adk_runtime.get_event_views(info.id)]
    assert ("tool_response", "consultar_regulamento") in before

    provider.configure_regulation_service(None)  # processo "novo": o Service é recriado
    second = build_adk_runtime(
        domain_session_factory=session_factory,
        session_db_url=f"sqlite+aiosqlite:///{(tmp_path / 'adk_sessions.db').as_posix()}",
        llm=ScriptedLlm(plan=plan),
    )
    try:
        await second.send_message(info.id, "Qual é a regra da piscina?")
        events = await second.get_event_views(info.id)
        assert [e.name for e in events if e.kind == "tool_response"].count("consultar_regulamento") == 2
    finally:
        await second.close()
