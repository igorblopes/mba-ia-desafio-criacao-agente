"""Testes estruturais da topologia multiagente (sem rede, sem Gemini)."""

from __future__ import annotations

import inspect

import pytest

from app.agents import concierge as concierge_module
from app.agents import reservations as reservations_module
from app.agents import visitors as visitors_module
from app.agents.concierge import build_concierge, concierge_agent, root_agent
from app.agents import regulation as regulation_module
from app.agents.regulation import build_regulation_agent, regulation_agent
from app.agents.reservations import build_reservation_agent, reservation_agent
from app.agents.visitors import build_visitor_agent, visitor_agent
from app.config import BASE_DIR, get_settings
from app.tools import REGULATION_TOOLS, RESERVATION_TOOLS, VISITOR_TOOLS

RESERVATION_NAMES = {
    "listar_minhas_reservas", "verificar_disponibilidade",
    "solicitar_reserva", "cancelar_minha_reserva",
}
VISITOR_NAMES = {"listar_meus_visitantes", "solicitar_autorizacao_visitante"}
REGULATION_NAMES = {"consultar_regulamento"}
PRIVILEGED = {"create_confirmed_reservation", "create_confirmed_authorization"}


def _tool_names(agent) -> set[str]:
    return {getattr(t, "name", getattr(t, "__name__", str(t))) for t in agent.tools}


def test_concierge_is_root_agent():
    assert root_agent is concierge_agent
    assert concierge_agent.name == "concierge_agent"
    assert concierge_agent.parent_agent is None
    assert reservation_agent.parent_agent is concierge_agent
    assert visitor_agent.parent_agent is concierge_agent
    assert regulation_agent.parent_agent is concierge_agent


def test_concierge_topology_has_three_specialists():
    # Concierge -> Reservation | Visitor | Regulation
    assert {a.name for a in concierge_agent.sub_agents} == {
        "reservation_agent", "visitor_agent", "regulation_agent"}
    assert len(concierge_agent.sub_agents) == 3


def test_concierge_has_no_business_tools():
    assert concierge_agent.tools == []


def test_reservation_agent_has_only_reservation_tools():
    assert _tool_names(reservation_agent) == RESERVATION_NAMES
    assert not (_tool_names(reservation_agent) & VISITOR_NAMES)
    assert reservation_agent.sub_agents == []


def test_visitor_agent_has_only_visitor_tools():
    assert _tool_names(visitor_agent) == VISITOR_NAMES
    assert not (_tool_names(visitor_agent) & RESERVATION_NAMES)
    assert visitor_agent.sub_agents == []


def test_regulation_agent_has_only_the_regulation_tool():
    assert _tool_names(regulation_agent) == REGULATION_NAMES  # uma única capacidade
    assert list(regulation_agent.tools) == list(REGULATION_TOOLS)
    assert not (_tool_names(regulation_agent) & (RESERVATION_NAMES | VISITOR_NAMES))
    assert regulation_agent.sub_agents == []
    assert not (_tool_names(concierge_agent) & REGULATION_NAMES)  # nunca no Concierge
    assert not (_tool_names(reservation_agent) & REGULATION_NAMES)
    assert not (_tool_names(visitor_agent) & REGULATION_NAMES)


def test_confirmed_internal_operations_are_not_exposed():
    for agent in (concierge_agent, reservation_agent, visitor_agent, regulation_agent):
        names = _tool_names(agent)
        assert not (names & PRIVILEGED)
        assert not any("confirm" in n for n in names)
        for t in agent.tools:
            assert getattr(t, "_require_confirmation", False) is False


def test_agents_use_the_shared_tool_objects():
    assert list(reservation_agent.tools) == list(RESERVATION_TOOLS)
    assert list(visitor_agent.tools) == list(VISITOR_TOOLS)


def test_model_comes_from_central_settings(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("GEMINI_MODEL", "modelo-de-teste")
    try:
        assert build_reservation_agent().model.model == "modelo-de-teste"
        assert build_visitor_agent().model.model == "modelo-de-teste"
        assert build_regulation_agent().model.model == "modelo-de-teste"
        assert build_concierge(
            reservation=build_reservation_agent(), visitor=build_visitor_agent()
        ).model.model == "modelo-de-teste"
    finally:
        get_settings.cache_clear()


def test_agents_retry_transient_gemini_failures():
    """Regressão (Passo 12): 429/503 momentâneos do Gemini viravam HTTP 500 no ensaio real."""
    for agent in (build_reservation_agent(), build_visitor_agent(), build_regulation_agent(),
                  build_concierge(reservation=build_reservation_agent(),
                                  visitor=build_visitor_agent())):
        retry = agent.model.retry_options
        assert retry is not None and retry.attempts > 1
        assert {429, 503} <= set(retry.http_status_codes)


def test_no_hardcoded_model_names_in_agent_modules():
    for mod in (concierge_module, reservations_module, visitors_module, regulation_module):
        src = inspect.getsource(mod).lower()
        assert "gemini-" not in src and "gemini_model" in src


def test_root_instruction_does_not_contain_regulation_content():
    regulamento = (BASE_DIR / "dados" / "regulamento.md").read_text(encoding="utf-8")
    first_line = next(l for l in regulamento.splitlines() if len(l.strip()) > 40)
    for agent in (concierge_agent, reservation_agent, visitor_agent, regulation_agent):
        assert first_line.strip() not in (agent.instruction or "")
        assert not agent.static_instruction
        assert len(agent.instruction) < 2000  # prompt enxuto, nunca o regulamento


def test_agent_modules_do_not_read_regulation_file():
    for mod in (concierge_module, reservations_module, visitors_module, regulation_module):
        src = inspect.getsource(mod)
        assert "regulamento.md" not in src
        assert "read_text" not in src and "open(" not in src


def test_agent_modules_do_not_touch_database_repositories_or_services():
    for mod in (concierge_module, reservations_module, visitors_module, regulation_module):
        src = inspect.getsource(mod)
        for forbidden in ("sqlalchemy", "app.database", "app.repositories", "app.services"):
            assert forbidden not in src, f"{mod.__name__} importa {forbidden}"


def test_no_agent_instruction_contains_any_regulation_text():
    """Nenhum agente carrega trecho do regulamento (nem o Regulation Agent): só a Tool o faz."""
    text = (BASE_DIR / "dados" / "regulamento.md").read_text(encoding="utf-8")
    sentences = {l.strip() for l in text.splitlines() if len(l.strip()) > 60}
    for agent in (concierge_agent, reservation_agent, visitor_agent, regulation_agent):
        prompt = f"{agent.instruction or ''}\n{agent.static_instruction or ''}"
        assert not any(sentence in prompt for sentence in sentences)
        assert len(prompt) < 3000


def test_regulation_agent_description_for_routing():
    assert "regulamento" in regulation_agent.description.lower()


@pytest.mark.parametrize("agent", [concierge_agent, reservation_agent, visitor_agent, regulation_agent])
def test_descriptions_present_for_delegation(agent):
    assert agent.description and len(agent.description) < 400
