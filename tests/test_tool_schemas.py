"""Prova quais argumentos o modelo enxerga em cada Tool pública."""

from __future__ import annotations

import json
import warnings

import pytest

from app.tools import PUBLIC_TOOLS, reservations, visitors

EXPECTED = {
    "listar_minhas_reservas": set(),
    "verificar_disponibilidade": {"area_id", "data"},
    "solicitar_reserva": {"area_id", "data"},
    "cancelar_minha_reserva": {"codigo"},
    "listar_meus_visitantes": set(),
    "solicitar_autorizacao_visitante": {"nome", "data"},
    "consultar_regulamento": {"pergunta"},
}
FORBIDDEN = {
    "apartamento", "apartment", "owner", "resident", "morador", "confirmed",
    "confirmation", "authorized", "autorizado", "force", "override", "bypass",
    "admin", "session_id", "tool_context",
    "path", "file_path", "filename", "chapter", "section", "top_k", "max_results", "max_chars",
    "full", "full_document", "all", "return_all", "return_full_document", "include_all",
}


def _declaration(tool):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return tool._get_declaration()


def _visible_params(tool) -> set[str]:
    decl = _declaration(tool)
    schema = decl.parameters_json_schema
    if schema is None and decl.parameters is not None:
        schema = decl.parameters.model_dump(exclude_none=True)
    return set((schema or {}).get("properties", {}))


def test_exactly_the_expected_public_tools():
    assert {t.name for t in PUBLIC_TOOLS} == set(EXPECTED)


@pytest.mark.parametrize("tool", PUBLIC_TOOLS, ids=lambda t: t.name)
def test_visible_parameters(tool):
    assert _visible_params(tool) == EXPECTED[tool.name]


@pytest.mark.parametrize("tool", PUBLIC_TOOLS, ids=lambda t: t.name)
def test_no_privileged_name_anywhere_in_schema(tool):
    decl = _declaration(tool)
    # Serialização completa: pega nomes em propriedades, descrições aninhadas, etc.
    blob = json.dumps(decl.model_dump(exclude_none=True), default=str).lower()
    params = _visible_params(tool)
    assert not (params & FORBIDDEN)
    for word in ("apartamento", "apartment", "confirmed", "confirmation", "force",
                 "override", "bypass", "tool_context"):
        assert word not in blob, f"{word!r} vazou no schema de {tool.name}"


def test_confirmed_operations_are_not_public():
    names = {t.name for t in PUBLIC_TOOLS}
    for mod in (reservations, visitors):
        assert not hasattr(mod, "create_confirmed_reservation")
        assert not hasattr(mod, "create_confirmed_authorization")
    assert not any("confirmed" in n or "confirm" in n for n in names)


def test_confirmation_is_dynamic_not_static():
    """A confirmação é dinâmica (request_confirmation); não há require_confirmation estático."""
    for tool in PUBLIC_TOOLS:
        assert tool._require_confirmation is False


@pytest.mark.parametrize("tool", PUBLIC_TOOLS, ids=lambda t: t.name)
def test_no_confirmation_parameters_visible_to_model(tool):
    visible = {p.lower() for p in _visible_params(tool)}
    for word in ("confirmed", "confirmation", "approval", "approved", "confirmation_id",
                 "invocation_id", "agent_name"):
        assert word not in visible


def test_regulation_tool_exposes_only_the_question():
    from app.tools.regulation import consultar_regulamento_tool

    assert _visible_params(consultar_regulamento_tool) == {"pergunta"}
    assert consultar_regulamento_tool._require_confirmation is False
