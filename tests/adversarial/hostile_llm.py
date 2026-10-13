"""ScriptedLlm que não entra em loop quando o "modelo" emite ``adk_request_confirmation``.

Um modelo real, ao ver o histórico, pararia de repetir; o ScriptedLlm puro repetiria a chamada até
o teto de 500 chamadas do ADK, o que mascara o que realmente fica persistido.
"""

from __future__ import annotations

from google.adk.models import LlmRequest, LlmResponse
from google.genai import types

from app.runtime.confirmations import CONFIRMATION_FUNCTION_NAME
from tests.fake_llm import ScriptedLlm


class HostileLlm(ScriptedLlm):
    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False):
        for content in llm_request.contents or []:
            if content.role == "model" and any(
                p.function_call and p.function_call.name == CONFIRMATION_FUNCTION_NAME
                for p in (content.parts or [])
            ):
                yield LlmResponse(content=types.Content(
                    role="model", parts=[types.Part(text="Concluído.")]))
                return
        async for response in super().generate_content_async(llm_request, stream):
            yield response
