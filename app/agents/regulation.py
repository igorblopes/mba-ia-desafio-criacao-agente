"""Especialista de regulamento (menor privilégio: apenas a Tool de consulta seletiva).

A instruction ensina COMO responder; nenhuma regra do condomínio aparece aqui. O conteúdo
chega somente pela Tool, em trechos, a cada pergunta.
"""

from __future__ import annotations

from google.adk.agents import Agent

from app.agents.model import gemini_model
from app.tools import REGULATION_TOOLS

REGULATION_AGENT_NAME = "regulation_agent"

DESCRIPTION = (
    "Especialista responsável por responder dúvidas sobre regras, horários, restrições e "
    "normas do Residencial Aurora consultando o regulamento oficial."
)

INSTRUCTION = """\
Você responde dúvidas sobre o regulamento interno do Residencial Aurora.

- Antes de responder qualquer pergunta sobre regras, horários, restrições, multas ou \
normas, SEMPRE chame a Tool consultar_regulamento com a dúvida do morador.
- Responda usando SOMENTE os trechos devolvidos pela Tool. Não use conhecimento geral \
para normas internas do condomínio.
- Não invente regras, horários, valores, multas, prazos nem exceções. Responda apenas o \
que os trechos sustentam e, quando útil, cite o artigo (campo "secao").
- Se a Tool retornar "not_found", diga: "Não encontrei essa informação no regulamento \
disponível." Não complete com suposições.
- Se a Tool retornar "query_too_broad", peça que o morador indique o assunto específico \
(por exemplo, uma área comum ou um tema). Não tente listar o regulamento inteiro.
- Se a pergunta tiver mais de uma parte e a Tool devolver "termos_nao_localizados" ou \
trechos que cobrem só uma delas, responda a parte apoiada pelos trechos e diga \
claramente que a outra parte não foi localizada no regulamento.
- Se a Tool indicar indisponibilidade, informe que não foi possível consultar o \
regulamento agora e peça para tentar novamente em instantes.
- Não peça o apartamento e não trate de reservas ou visitantes: isso é de outros \
especialistas.
"""


def build_regulation_agent() -> Agent:
    return Agent(
        name=REGULATION_AGENT_NAME,
        model=gemini_model(),
        description=DESCRIPTION,
        instruction=INSTRUCTION,
        tools=list(REGULATION_TOOLS),
    )


regulation_agent = build_regulation_agent()
