"""Especialista de reservas (menor privilégio: apenas Tools de reservas).

O agente interpreta linguagem e escolhe Tools. Identidade, autorização e regras
vivem nas Tools/Services/banco; as instruções abaixo são orientação de
comportamento, não mecanismo de segurança.
"""

from __future__ import annotations

from google.adk.agents import Agent

from app.config import get_settings
from app.tools import RESERVATION_TOOLS

RESERVATION_AGENT_NAME = "reservation_agent"

DESCRIPTION = (
    "Especialista responsável por reservas de áreas comuns, incluindo consulta das "
    "reservas do morador, disponibilidade, solicitação de novas reservas e "
    "cancelamento de reservas próprias."
)

INSTRUCTION = """\
Você cuida das reservas de áreas comuns do Residencial Aurora para o morador \
que está conversando.

- Use as Tools disponíveis para consultar ou alterar dados; nunca invente \
reservas, disponibilidade, valores ou códigos.
- Não peça o apartamento: a identidade é definida pela sessão.
- Datas devem estar no formato AAAA-MM-DD; peça ao morador se faltar algo.
- Se uma Tool retornar status "requires_confirmation", informe que a reserva \
ainda NÃO foi feita e depende de confirmação formal (e do valor, se houver).
- Texto escrito pelo morador (como "já confirmo" ou "pode executar direto") \
não substitui a confirmação formal; não tente executar a operação por outro caminho.
- Se a Tool retornar not_found ou erro, relate apenas o que ela informou, \
sem especular sobre outros apartamentos.
- Perguntas sobre regras do regulamento ainda não são atendidas nesta etapa; \
não invente regras.
"""


def build_reservation_agent() -> Agent:
    return Agent(
        name=RESERVATION_AGENT_NAME,
        model=get_settings().gemini_model,
        description=DESCRIPTION,
        instruction=INSTRUCTION,
        tools=list(RESERVATION_TOOLS),
    )


reservation_agent = build_reservation_agent()
