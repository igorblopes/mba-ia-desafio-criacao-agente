"""LLM roteirizado para testar a topologia com Runner/ADK reais, sem rede.

Só o *modelo* é falso; transferência de agente, execução de Tools, ToolContext,
Services e banco são os reais. Serve para provar mecânica (delegação, eventos,
identidade vinda da sessão), não a qualidade do roteamento do Gemini.
"""

from __future__ import annotations

from typing import Callable

from google.adk.models import BaseLlm, LlmRequest, LlmResponse
from google.genai import types

Plan = Callable[[str, str], tuple[str, dict] | None]


class ScriptedLlm(BaseLlm):
    """``plan(agent_kind, user_text)`` -> (nome_da_função, args) ou None para só texto."""

    model: str = "scripted"
    plan: object = None

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False):
        contents = llm_request.contents or []
        last = contents[-1] if contents else None
        if last and any(p.function_response for p in (last.parts or [])):
            yield LlmResponse(content=types.Content(
                role="model", parts=[types.Part(text="Concluído.")]))
            return
        instruction = str(llm_request.config.system_instruction or "")
        # o ADK injeta 'Your internal name is "<nome>"' na instrução do agente atual
        kinds = {"concierge_agent": "concierge", "reservation_agent": "reservation",
                 "visitor_agent": "visitor",
                 "regulation_agent": "regulation"}
        found = [k for name, k in kinds.items() if f'internal name is "{name}"' in instruction]
        assert len(found) == 1, instruction[:300]
        kind = found[0]
        # Última mensagem textual REAL do usuário (permite várias mensagens na mesma sessão).
        # Após uma transferência o ADK injeta o histórico de outros agentes como texto de role
        # user ("[agente] ... BEGIN_QUOTED_AGENT_CONTENT"); isso não é fala do morador.
        user_text = next(
            (p.text for c in reversed(contents) if c.role == "user"
             for p in (c.parts or [])
             if p.text and "BEGIN_QUOTED_AGENT_CONTENT" not in p.text
             and not p.text.startswith("For context")), ""
        )
        step = self.plan(kind, user_text)  # type: ignore[operator]
        if step is None:
            parts = [types.Part(text="Sem ação.")]
        else:
            name, args = step
            parts = [types.Part(function_call=types.FunctionCall(name=name, args=args))]
        yield LlmResponse(content=types.Content(role="model", parts=parts))
