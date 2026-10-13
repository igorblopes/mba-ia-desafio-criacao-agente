"""App FastAPI com LLM roteirizado para o teste de restart REAL (processo uvicorn de verdade).

    uvicorn tests.api_server:app --port 8765     (bancos vêm de DOMAIN_DATABASE_URL e
                                                  ADK_SESSION_DATABASE_URL no ambiente)
"""

from app.main import create_app
from app.runtime.adk_runtime import build_adk_runtime
from tests.fake_llm import ScriptedLlm
from tests.scripted_plan import plan

app = create_app(lambda: build_adk_runtime(llm=ScriptedLlm(plan=plan)))
