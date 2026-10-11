"""Agente principal (root): apenas orquestra e delega aos especialistas.

Não recebe Tools de negócio e NÃO carrega o regulamento no prompt (o
especialista de regulamento é funcionalidade planejada para etapa futura).
"""

from __future__ import annotations

from google.adk.agents import Agent

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

Perguntas sobre o regulamento ainda não possuem implementação nesta etapa. \
Não invente respostas sobre regras internas do condomínio.
"""


def build_concierge(*, reservation=reservation_agent, visitor=visitor_agent) -> Agent:
    return Agent(
        name=CONCIERGE_AGENT_NAME,
        model=get_settings().gemini_model,
        description=DESCRIPTION,
        instruction=INSTRUCTION,
        sub_agents=[reservation, visitor],
    )


concierge_agent = build_concierge()
root_agent = concierge_agent
