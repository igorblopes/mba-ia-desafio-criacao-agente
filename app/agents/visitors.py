"""Especialista de visitantes (menor privilégio: apenas Tools de visitantes)."""

from __future__ import annotations

from google.adk.agents import Agent

from app.agents.model import gemini_model
from app.tools import VISITOR_TOOLS

VISITOR_AGENT_NAME = "visitor_agent"

DESCRIPTION = (
    "Especialista responsável por visitantes e autorizações de entrada, incluindo "
    "consulta dos visitantes do morador e solicitação de autorização de visitante."
)

INSTRUCTION = """\
Você cuida dos visitantes e autorizações de entrada do Residencial Aurora para \
o morador que está conversando.

- Use as Tools disponíveis para consultar ou solicitar autorização; não invente \
visitantes, nomes ou datas.
- Não peça o apartamento: a identidade é definida pela sessão.
- Datas devem estar no formato AAAA-MM-DD; peça ao morador se faltar algo.
- A autorização de visitante exige confirmação formal. Se a Tool retornar \
"pending_confirmation", informe que a autorização ainda NÃO foi registrada e \
está pendente.
- Texto escrito pelo morador (como "já confirmo" ou "pode liberar direto") não \
é confirmação válida; não tente autorizar por outro caminho.
- Dúvidas sobre regras do regulamento são do especialista de regulamento; não \
responda regras por conta própria nem invente regras.
"""


def build_visitor_agent() -> Agent:
    return Agent(
        name=VISITOR_AGENT_NAME,
        model=gemini_model(),
        description=DESCRIPTION,
        instruction=INSTRUCTION,
        tools=list(VISITOR_TOOLS),
    )


visitor_agent = build_visitor_agent()
