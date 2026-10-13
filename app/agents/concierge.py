"""Agente principal (root): apenas orquestra e delega aos especialistas.

Não recebe Tools de negócio e NÃO carrega o regulamento no prompt: dúvidas sobre regras
vão ao Regulation Agent, que recupera apenas os trechos necessários por meio de uma Tool.
"""

from __future__ import annotations

from google.adk.agents import Agent

from app.agents.regulation import build_regulation_agent, regulation_agent
from app.agents.reservations import reservation_agent
from app.agents.visitors import visitor_agent
from app.config import get_settings

CONCIERGE_AGENT_NAME = "concierge_agent"

DESCRIPTION = "Assistente principal do Residencial Aurora; encaminha o morador ao especialista adequado."

INSTRUCTION = """\
Você é o assistente principal do Residencial Aurora.

Identifique a necessidade do morador e encaminhe ao especialista adequado.

Assuntos de reservas devem ser tratados pelo especialista de reservas.

Assuntos de visitantes e autorizações de entrada devem ser tratados pelo \
especialista de visitantes.

Não invente dados do condomínio.

Não execute regras de negócio diretamente.

Não solicite apartamento para executar operações.

Questões sobre regras, normas, horários de funcionamento e restrições do \
condomínio devem ser tratadas pelo especialista de regulamento.

Não responda regras do condomínio por conta própria.
"""


def build_concierge(
    *, reservation=reservation_agent, visitor=visitor_agent, regulation=None
) -> Agent:
    """``regulation=None`` cria um especialista novo (um agente ADK só pode ter um pai)."""
    if regulation is None:
        regulation = build_regulation_agent()
    return Agent(
        name=CONCIERGE_AGENT_NAME,
        model=get_settings().gemini_model,
        description=DESCRIPTION,
        instruction=INSTRUCTION,
        sub_agents=[reservation, visitor, regulation],
    )


concierge_agent = build_concierge(regulation=regulation_agent)
root_agent = concierge_agent
