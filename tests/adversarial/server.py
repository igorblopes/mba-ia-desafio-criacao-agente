"""App FastAPI com o modelo HOSTIL para os ataques contra processo uvicorn real.

    uvicorn tests.adversarial.server:app   (DOMAIN_DATABASE_URL / ADK_SESSION_DATABASE_URL no ambiente)

``ADV_CRASH_AFTER_EFFECT=1`` injeta uma falha de processo (``os._exit``) logo DEPOIS do efeito de
domínio e ANTES de a confirmação ser finalizada (ADV-025). Fora dessa variável, nada é alterado.
"""

import os

from app.main import create_app
from app.runtime.adk_runtime import build_adk_runtime
from tests.adversarial.hostile_llm import HostileLlm
from tests.adversarial.hostile_plan import plan

if os.environ.get("ADV_CRASH_AFTER_EFFECT"):
    from app.services.confirmation_service import ConfirmationService

    async def _crash(self, record):  # noqa: ANN001
        os._exit(86)

    ConfirmationService.mark_approved = _crash  # type: ignore[method-assign]

app = create_app(lambda: build_adk_runtime(llm=HostileLlm(plan=plan)))
